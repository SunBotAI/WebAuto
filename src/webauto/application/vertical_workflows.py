"""Persistent shopping and Xianyu workflows built on governed WebAuto runs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from webauto.domain import (
    Action,
    ActionKind,
    IdempotencyClass,
    RiskLevel,
    VerifierSpec,
)
from webauto.scenarios import (
    ProductCandidate,
    ShoppingAdvisor,
    ShoppingRequest,
    assess_second_hand_risk,
    deduplicate_products,
    inquiry_draft,
)

from .service import Actor, ApplicationService

SHOPPING_WORKSPACES = "shopping_workspaces"
XIANYU_BUY_WORKSPACES = "xianyu_buy_workspaces"
XIANYU_LISTING_WORKSPACES = "xianyu_listing_workspaces"
XIANYU_STORE_WORKSPACES = "xianyu_store_workspaces"
ACTION_PREVIEWS = "action_previews"
VERTICAL_RESOURCE_CATEGORIES = frozenset(
    {
        SHOPPING_WORKSPACES,
        XIANYU_BUY_WORKSPACES,
        XIANYU_LISTING_WORKSPACES,
        XIANYU_STORE_WORKSPACES,
        ACTION_PREVIEWS,
    }
)

_MONEY = re.compile(r"-?\d+(?:\.\d+)?")
_BUDGET = re.compile(r"(?:预算|不超过|最多|以内)\s*[¥￥]?\s*(\d+(?:\.\d+)?)")
_QUANTITY = re.compile(r"(?:要|买|数量)?\s*(\d+)\s*(?:件|个|台|份|套)\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_shopping_request(
    message: str, overrides: dict[str, Any] | None = None
) -> ShoppingRequest:
    """Compile a conservative shopping request without inventing requirements."""

    values = dict(overrides or {})
    budget_match = _BUDGET.search(message)
    quantity_match = _QUANTITY.search(message)
    query = str(values.pop("query", "")).strip()
    if not query:
        query = _BUDGET.sub("", message)
        query = re.sub(r"(?:只看|不要买|不要下单|帮我|请|比较|比价)", " ", query)
        query = " ".join(query.split()).strip("，。,. ") or message.strip()
    if "budget" not in values and budget_match:
        values["budget"] = budget_match.group(1)
    if "quantity" not in values and quantity_match:
        values["quantity"] = int(quantity_match.group(1))
    values.setdefault(
        "allow_used", not any(word in message for word in ("只要全新", "不要二手", "全新"))
    )
    values.setdefault(
        "read_only",
        not any(word in message for word in ("加入购物车", "下单", "购买", "立即买")),
    )
    return ShoppingRequest(query=query, **values)


def normalize_product_candidate(raw: dict[str, Any], *, quantity: int = 1) -> ProductCandidate:
    """Normalize one agent/site-skill record into the cross-site product contract."""

    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    merged = {**fields, **{key: value for key, value in raw.items() if key != "fields"}}
    url = str(merged.get("url") or merged.get("source_url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("candidate requires an HTTP(S) source URL")
    platform = str(merged.get("platform") or _platform_from_host(parsed.hostname)).strip()
    title = str(merged.get("title") or merged.get("name") or "").strip()
    if not title:
        raise ValueError("candidate title is required")
    item_id = str(merged.get("item_id") or merged.get("id") or _item_id(url)).strip()
    price = _decimal(merged.get("price"), field="price")
    shipping = _decimal(merged.get("shipping", 0), field="shipping")
    score = merged.get("seller_score", merged.get("rating"))
    seller_score = None if score in {None, ""} else float(score)
    if seller_score is not None and seller_score > 1:
        seller_score = seller_score / 5 if seller_score <= 5 else seller_score / 100
    seller_score = None if seller_score is None else max(0.0, min(seller_score, 1.0))
    evidence = merged.get("evidence") if isinstance(merged.get("evidence"), dict) else {}
    evidence_urls = merged.get("evidence_urls") or []
    for index, evidence_url in enumerate(evidence_urls, 1):
        evidence.setdefault(f"source_{index}", str(evidence_url))
    evidence.setdefault("product_page", url)
    specs = merged.get("specs") if isinstance(merged.get("specs"), dict) else {}
    flags = merged.get("risk_flags") if isinstance(merged.get("risk_flags"), list) else []
    in_stock = merged.get("in_stock")
    if isinstance(in_stock, str):
        in_stock = in_stock.strip().lower() not in {"false", "0", "no", "out", "缺货", "无货"}
    return ProductCandidate(
        platform=platform,
        item_id=item_id,
        title=title,
        url=url,
        price=price,
        shipping=shipping,
        quantity=int(merged.get("quantity") or quantity),
        condition=str(merged.get("condition") or "unknown"),
        in_stock=in_stock if isinstance(in_stock, bool) else None,
        seller=str(merged["seller"]) if merged.get("seller") is not None else None,
        seller_score=seller_score,
        specs={str(key): str(value) for key, value in specs.items()},
        evidence={str(key): str(value) for key, value in evidence.items()},
        risk_flags=[str(value) for value in flags],
    )


class VerticalWorkflowService:
    """Scenario services; selectors and browser versions stay outside this layer."""

    def __init__(self, application: ApplicationService) -> None:
        self.application = application

    async def create_shopping_workspace(
        self,
        actor: Actor,
        *,
        source_run_id: str,
        message: str,
        candidates: list[dict[str, Any]],
        request_overrides: dict[str, Any] | None = None,
        uncertainties: list[str] | None = None,
    ) -> dict[str, Any]:
        await self.application.get_run(actor, source_run_id)
        request = parse_shopping_request(message, request_overrides)
        normalized: list[ProductCandidate] = []
        rejected: list[str] = []
        for index, raw in enumerate(candidates):
            try:
                normalized.append(normalize_product_candidate(raw, quantity=request.quantity))
            except (TypeError, ValueError, InvalidOperation) as exc:
                rejected.append(f"candidate[{index}]: {exc}")
        normalized = deduplicate_products(normalized)
        ranked = ShoppingAdvisor().rank(request, normalized)
        workspace_id = str(uuid4())
        workspace = {
            "schema_version": "1.0",
            "id": workspace_id,
            "kind": "shopping",
            "source_run_id": source_run_id,
            "status": "candidates_ready" if ranked else "needs_more_evidence",
            "request": request.model_dump(mode="json"),
            "result_card": {
                "candidate_count": len(ranked),
                "eligible_count": sum(item.eligible for item in ranked),
                "recommended_key": (
                    _candidate_key(ranked[0].product) if ranked and ranked[0].eligible else None
                ),
                "ranked": [
                    {
                        "key": _candidate_key(item.product),
                        "eligible": item.eligible,
                        "score": round(item.score, 6),
                        "reasons": item.reasons,
                        "product": item.product.model_dump(mode="json"),
                    }
                    for item in ranked
                ],
                "uncertainties": list(dict.fromkeys([*(uncertainties or []), *rejected])),
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(actor, SHOPPING_WORKSPACES, workspace_id, workspace)
        return workspace

    async def create_xianyu_buy_workspace(
        self,
        actor: Actor,
        *,
        source_run_id: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        await self.application.get_run(actor, source_run_id)
        assessment = assess_second_hand_risk(item)
        workspace_id = str(uuid4())
        workspace = {
            "schema_version": "1.0",
            "id": workspace_id,
            "kind": "xianyu_buy",
            "source_run_id": source_run_id,
            "status": "risk_review_ready",
            "item": dict(item),
            "risk_assessment": assessment.model_dump(mode="json"),
            "inquiry_drafts": inquiry_draft(item),
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(
            actor, XIANYU_BUY_WORKSPACES, workspace_id, workspace
        )
        return workspace

    async def create_xianyu_listing_workspace(
        self,
        actor: Actor,
        *,
        source_run_id: str,
        draft: dict[str, Any],
        image_grants: list[dict[str, Any]],
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.application.get_run(actor, source_run_id)
        required = ("title", "description", "price", "category", "condition")
        missing = [key for key in required if not str(draft.get(key, "")).strip()]
        if missing:
            raise ValueError("listing draft missing fields: " + ", ".join(missing))
        price = _decimal(draft["price"], field="price")
        if price <= 0:
            raise ValueError("listing price must be positive")
        if not image_grants:
            raise ValueError("listing requires at least one run-authorized image")
        safe_images = [
            {
                "file_id": str(item["file_id"]),
                "filename": str(item["filename"]),
                "sha256": str(item["sha256"]),
            }
            for item in image_grants
        ]
        current = {
            "title": str(draft["title"]).strip(),
            "description": str(draft["description"]).strip(),
            "price": str(price),
            "category": str(draft["category"]).strip(),
            "condition": str(draft["condition"]).strip(),
            "images": safe_images,
        }
        before = previous or {}
        diff = {
            key: {"before": before.get(key), "after": value}
            for key, value in current.items()
            if before.get(key) != value
        }
        digest = _digest(current)
        workspace_id = str(uuid4())
        workspace = {
            "schema_version": "1.0",
            "id": workspace_id,
            "kind": "xianyu_listing",
            "source_run_id": source_run_id,
            "status": "draft_ready",
            "draft": current,
            "diff": diff,
            "digest": digest,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(
            actor, XIANYU_LISTING_WORKSPACES, workspace_id, workspace
        )
        return workspace

    async def create_xianyu_store_workspace(
        self,
        actor: Actor,
        *,
        source_run_id: str,
        records: list[dict[str, Any]],
        uncertainties: list[str] | None = None,
    ) -> dict[str, Any]:
        await self.application.get_run(actor, source_run_id)
        buckets: dict[str, list[dict[str, Any]]] = {
            "items": [],
            "messages": [],
            "orders": [],
            "other": [],
        }
        for record in records:
            kind = str(record.get("kind") or "other").lower()
            bucket = {
                "item": "items",
                "listing": "items",
                "message": "messages",
                "order": "orders",
            }.get(kind, "other")
            buckets[bucket].append(dict(record))
        workspace_id = str(uuid4())
        workspace = {
            "schema_version": "1.0",
            "id": workspace_id,
            "kind": "xianyu_store",
            "source_run_id": source_run_id,
            "status": "snapshot_ready",
            "snapshot": buckets,
            "uncertainties": list(uncertainties or []),
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(
            actor, XIANYU_STORE_WORKSPACES, workspace_id, workspace
        )
        return workspace

    async def get_workspace(self, actor: Actor, category: str, workspace_id: str) -> dict[str, Any]:
        if category not in VERTICAL_RESOURCE_CATEGORIES - {ACTION_PREVIEWS}:
            raise ValueError("unsupported vertical workspace category")
        return await self._resource(actor, category, workspace_id)

    async def prepare_action(
        self,
        actor: Actor,
        *,
        workspace_category: str,
        workspace_id: str,
        operation: str,
        object_scope: dict[str, Any],
        preview: dict[str, Any],
        page_revision: str,
        evidence_ids: list[str],
        source_url: str,
        available_files: list[dict[str, str]] | None = None,
        allowed_domains: list[str] | None = None,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        if ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ValueError("approval ttl must be between 1 and 86400 seconds")
        workspace = await self.get_workspace(actor, workspace_category, workspace_id)
        object_scope = _canonical_operation_scope(
            workspace=workspace,
            operation=operation,
            requested=object_scope,
            preview=preview,
        )
        parsed_source = urlparse(source_url)
        if parsed_source.scheme not in {"http", "https"} or not parsed_source.hostname:
            raise ValueError("governed action requires an HTTP(S) source URL")
        domains = list(
            dict.fromkeys(
                str(value).strip()
                for value in (allowed_domains or [parsed_source.hostname])
                if str(value).strip()
            )
        )
        safe_files = [
            {
                "file_id": str(item["file_id"]),
                "sha256": str(item["sha256"]),
            }
            for item in (available_files or [])
        ]
        bound_scope = {
            **object_scope,
            "operation": operation,
            "source_url": source_url,
            "allowed_domains": domains,
            "files": safe_files,
        }
        source_run = await self.application.get_run(actor, workspace["source_run_id"])
        final_control = str(preview.get("button_text") or "").strip()
        if operation != "payment" and not final_control:
            raise ValueError("governed action preview requires the exact final button_text")
        bound_scope.update(
            {
                "final_control": final_control,
                "page_revision": page_revision,
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
            }
        )
        if operation == "payment":
            return await self._prepare_payment_handoff(
                actor, workspace_category, workspace, bound_scope, preview, source_url
            )
        action_template = _operation_action(
            operation, object_scope=bound_scope, approval_id="pending-approval"
        )
        goal = await self.application.create_goal(
            actor,
            objective=f"Execute approved vertical operation: {operation}",
            success_criteria=["页面状态或业务查询确认写操作结果"],
            constraints={"operation": operation, "workspace_id": workspace_id},
        )
        action_run = await self.application.create_run(
            actor,
            goal_id=goal.id,
            plan_id="vertical-action-" + uuid4().hex,
            placement=source_run.placement,
            profile_id=source_run.profile_id,
        )
        await self.application.start_run(actor, action_run.id)
        approval = await self.application.request_approval(
            actor,
            run_id=action_run.id,
            step_id=operation,
            action=action_template,
            preview=preview,
            diff={"operation": {"before": "not_executed", "after": operation}},
            page_revision=page_revision,
            evidence_ids=evidence_ids,
            object_scope=bound_scope,
            ttl=timedelta(seconds=ttl_seconds),
        )
        await self.application.wait_for_approval(actor, action_run.id)
        preview_id = str(uuid4())
        record = {
            "schema_version": "1.0",
            "id": preview_id,
            "workspace_category": workspace_category,
            "workspace_id": workspace_id,
            "action_run_id": action_run.id,
            "operation": operation,
            "state": "waiting_approval",
            "approval_id": approval.id,
            "action": action_template.model_dump(mode="json"),
            "preview": preview,
            "object_scope": bound_scope,
            "page_revision": page_revision,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "source_url": source_url,
            "available_files": safe_files,
            "allowed_domains": domains,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(actor, ACTION_PREVIEWS, preview_id, record)
        await self._update_workspace(
            actor,
            workspace_category,
            workspace,
            status="waiting_approval",
            last_action_preview_id=preview_id,
        )
        return record

    async def get_action_preview(self, actor: Actor, preview_id: str) -> dict[str, Any]:
        return await self._resource(actor, ACTION_PREVIEWS, preview_id)

    async def consume_action(self, actor: Actor, preview_id: str) -> dict[str, Any]:
        record = await self.get_action_preview(actor, preview_id)
        if record["state"] != "waiting_approval":
            raise RuntimeError("action preview is not waiting for approval")
        action = Action.model_validate({**record["action"], "approval_id": record["approval_id"]})
        await self.application.consume_approval(
            actor,
            record["approval_id"],
            action=action,
            page_revision=record["page_revision"],
            evidence_ids=record["evidence_ids"],
            object_scope=record["object_scope"],
        )
        await self.application.continue_after_approval(actor, record["action_run_id"])
        updated = {
            **record,
            "state": "approved_once",
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(actor, ACTION_PREVIEWS, preview_id, updated)
        return updated

    async def record_action_result(
        self,
        actor: Actor,
        preview_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        record = await self.get_action_preview(actor, preview_id)
        updated = {
            **record,
            "state": status,
            "result": dict(result),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(actor, ACTION_PREVIEWS, preview_id, updated)
        workspace = await self.get_workspace(
            actor, record["workspace_category"], record["workspace_id"]
        )
        await self._update_workspace(
            actor,
            record["workspace_category"],
            workspace,
            status=status,
            last_action_preview_id=preview_id,
        )
        return updated

    async def process_agent_result(
        self,
        actor: Actor,
        *,
        run_id: str,
        intent: str,
        message: str,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach a vertical workspace when a dynamic agent returned entities."""

        result = dict(output)
        agent = result.get("agent_result") if isinstance(result.get("agent_result"), dict) else {}
        agent_output = agent.get("output") if isinstance(agent.get("output"), dict) else {}
        entities = (
            agent_output.get("entities") if isinstance(agent_output.get("entities"), list) else []
        )
        uncertainties = (
            agent.get("uncertainties") if isinstance(agent.get("uncertainties"), list) else []
        )
        if intent in {"shopping", "xianyu_buy"}:
            products = [
                item
                for item in entities
                if isinstance(item, dict) and item.get("kind") in {"product", "xianyu_item"}
            ]
            shopping = await self.create_shopping_workspace(
                actor,
                source_run_id=run_id,
                message=message,
                candidates=products,
                uncertainties=[str(item) for item in uncertainties],
            )
            result["shopping_workspace"] = shopping
            if intent == "xianyu_buy" and products:
                raw_item = _entity_to_xianyu_item(products[0])
                result["xianyu_buy_workspace"] = await self.create_xianyu_buy_workspace(
                    actor, source_run_id=run_id, item=raw_item
                )
        elif intent == "xianyu_manage":
            result["xianyu_store_workspace"] = await self.create_xianyu_store_workspace(
                actor,
                source_run_id=run_id,
                records=[item for item in entities if isinstance(item, dict)],
                uncertainties=[str(item) for item in uncertainties],
            )
        return result

    async def _prepare_payment_handoff(
        self,
        actor: Actor,
        category: str,
        workspace: dict[str, Any],
        object_scope: dict[str, Any],
        preview: dict[str, Any],
        source_url: str,
    ) -> dict[str, Any]:
        source_run = await self.application.get_run(actor, workspace["source_run_id"])
        goal = await self.application.create_goal(
            actor,
            objective="Human payment takeover",
            success_criteria=["用户在专属浏览器中自行确认或取消支付"],
            constraints={"operation": "payment", "automation": "forbidden"},
        )
        run = await self.application.create_run(
            actor,
            goal_id=goal.id,
            plan_id="human-payment-" + uuid4().hex,
            placement=source_run.placement,
            profile_id=source_run.profile_id,
        )
        await self.application.start_run(actor, run.id)
        await self.application.takeover(actor, run.id)
        preview_id = str(uuid4())
        record = {
            "schema_version": "1.0",
            "id": preview_id,
            "workspace_category": category,
            "workspace_id": workspace["id"],
            "action_run_id": run.id,
            "operation": "payment",
            "state": "waiting_human",
            "preview": preview,
            "object_scope": object_scope,
            "source_url": source_url,
            "automation_allowed": False,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        await self.application.upsert_resource(actor, ACTION_PREVIEWS, preview_id, record)
        await self._update_workspace(
            actor, category, workspace, status="waiting_human", last_action_preview_id=preview_id
        )
        return record

    async def _update_workspace(
        self,
        actor: Actor,
        category: str,
        workspace: dict[str, Any],
        **changes: Any,
    ) -> dict[str, Any]:
        updated = {**workspace, **changes, "updated_at": utc_now()}
        await self.application.upsert_resource(actor, category, workspace["id"], updated)
        return updated

    async def _resource(self, actor: Actor, category: str, resource_id: str) -> dict[str, Any]:
        values = await self.application.list_resources(actor, category, resource_ids=[resource_id])
        if resource_id not in values:
            raise KeyError(f"{category} resource was not found")
        return dict(values[resource_id])


def _canonical_operation_scope(
    *,
    workspace: dict[str, Any],
    operation: str,
    requested: dict[str, Any],
    preview: dict[str, Any],
) -> dict[str, Any]:
    kind = workspace.get("kind")
    if kind == "shopping" and operation in {
        "add_to_cart",
        "start_checkout",
        "place_order",
        "payment",
    }:
        key = str(requested.get("candidate_key") or "")
        ranked = workspace.get("result_card", {}).get("ranked", [])
        selected = next((item for item in ranked if item.get("key") == key), None)
        if selected is None:
            raise ValueError("shopping action candidate is not in this workspace")
        product = selected["product"]
        return {
            "candidate_key": key,
            "platform": product["platform"],
            "item_id": product["item_id"],
            "sku_id": requested.get("sku_id"),
            "quantity": int(requested.get("quantity") or product.get("quantity") or 1),
            "unit_price": str(product["price"]),
            "shipping": str(product.get("shipping", "0")),
            "total_price": str(product["total_price"]),
            "seller": product.get("seller"),
            "product_url": str(product["url"]),
            "address_masked": str(requested.get("address_masked") or "未提供"),
        }
    if kind == "xianyu_buy" and operation == "xianyu_send_message":
        message = str(preview.get("message") or requested.get("message") or "").strip()
        if not message:
            raise ValueError("Xianyu inquiry preview requires the exact message text")
        item = workspace["item"]
        return {
            "item_id": str(item.get("item_id") or item.get("id") or "unknown"),
            "item_url": str(item.get("url") or ""),
            "message": message,
        }
    if kind == "xianyu_listing" and operation == "xianyu_publish":
        draft = workspace["draft"]
        return {
            "listing_digest": workspace["digest"],
            "title": draft["title"],
            "price": draft["price"],
            "category": draft["category"],
            "condition": draft["condition"],
            "image_sha256s": [item["sha256"] for item in draft["images"]],
        }
    if kind == "xianyu_store" and operation in {
        "xianyu_update_price",
        "xianyu_downlist",
        "xianyu_reply",
    }:
        key = "message_id" if operation == "xianyu_reply" else "listing_id"
        record_id = str(requested.get(key) or "")
        if not record_id:
            raise ValueError(f"store action requires {key}")
        bucket = "messages" if operation == "xianyu_reply" else "items"
        records = workspace.get("snapshot", {}).get(bucket, [])
        record = next(
            (
                value
                for value in records
                if str(value.get("id") or value.get(key) or value.get("item_id") or "") == record_id
            ),
            None,
        )
        if record is None:
            raise ValueError("store action record is not in the current snapshot")
        scope = {
            key: record_id,
            "record_digest": _digest(record),
            "previous_status": record.get("status"),
        }
        if operation == "xianyu_update_price":
            scope["old_price"] = record.get("price")
            scope["new_price"] = str(_decimal(requested.get("new_price"), field="new_price"))
        if operation == "xianyu_reply":
            reply = str(preview.get("message") or requested.get("message") or "").strip()
            if not reply:
                raise ValueError("store reply requires the exact message text")
            scope["message"] = reply
        return scope
    raise ValueError(f"operation {operation} is not valid for {kind} workspace")


def _operation_action(operation: str, *, object_scope: dict[str, Any], approval_id: str) -> Action:
    definitions: dict[str, tuple[RiskLevel, IdempotencyClass, str]] = {
        "add_to_cart": (RiskLevel.L2, IdempotencyClass.IDEMPOTENT, "cart_contains"),
        "start_checkout": (
            RiskLevel.L2,
            IdempotencyClass.IDEMPOTENT,
            "checkout_preview_opened",
        ),
        "place_order": (RiskLevel.L3, IdempotencyClass.NON_IDEMPOTENT, "order_created"),
        "xianyu_send_message": (RiskLevel.L2, IdempotencyClass.NON_IDEMPOTENT, "message_sent"),
        "xianyu_publish": (RiskLevel.L3, IdempotencyClass.NON_IDEMPOTENT, "listing_published"),
        "xianyu_update_price": (RiskLevel.L3, IdempotencyClass.NON_IDEMPOTENT, "price_updated"),
        "xianyu_downlist": (RiskLevel.L3, IdempotencyClass.IDEMPOTENT, "listing_downlisted"),
        "xianyu_reply": (RiskLevel.L2, IdempotencyClass.NON_IDEMPOTENT, "message_sent"),
    }
    if operation not in definitions:
        raise ValueError(f"unsupported governed operation: {operation}")
    risk, idempotency, effect = definitions[operation]
    target = {
        "operation": operation,
        **{
            key: value
            for key, value in object_scope.items()
            if key in {"item_id", "sku_id", "order_id", "message_id", "listing_id"}
        },
    }
    return Action(
        kind=ActionKind.CLICK,
        target=target,
        arguments={"object_digest": _digest(object_scope)},
        preconditions=[
            "page_revision_matches",
            "evidence_matches",
            "object_scope_matches",
            "approval_valid",
        ],
        expected_effect={effect: True},
        risk_level=risk,
        idempotency=idempotency,
        verifier=VerifierSpec(kind="business_query", expectation={effect: True}),
        approval_id=approval_id,
    )


def _entity_to_xianyu_item(entity: dict[str, Any]) -> dict[str, Any]:
    fields = entity.get("fields") if isinstance(entity.get("fields"), dict) else {}
    return {
        **fields,
        "title": entity.get("title") or fields.get("title"),
        "url": entity.get("url") or fields.get("url"),
        "price": entity.get("price") or fields.get("price"),
        "description": fields.get("description", ""),
        "real_photos": fields.get("real_photos", False),
    }


def _candidate_key(candidate: ProductCandidate) -> str:
    return f"{candidate.platform.lower()}:{candidate.item_id}"


def _platform_from_host(host: str) -> str:
    host = host.lower()
    if "taobao" in host or "tmall" in host:
        return "taobao"
    if host.endswith("jd.com") or ".jd.com" in host:
        return "jd"
    if "goofish" in host or "xianyu" in host:
        return "xianyu"
    return host


def _item_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("id", "itemId", "item_id", "sku", "skuId"):
        if query.get(key):
            return str(query[key][0])
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return (
        tail
        if tail and tail not in {"item", "product"}
        else hashlib.sha256(url.encode()).hexdigest()[:20]
    )


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    raw = "" if value is None else str(value)
    match = _MONEY.search(raw.replace(",", ""))
    if not match:
        raise ValueError(f"candidate {field} is missing or invalid")
    return Decimal(match.group(0))


def _digest(value: Any) -> str:
    import json

    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ACTION_PREVIEWS",
    "SHOPPING_WORKSPACES",
    "VERTICAL_RESOURCE_CATEGORIES",
    "XIANYU_BUY_WORKSPACES",
    "XIANYU_LISTING_WORKSPACES",
    "XIANYU_STORE_WORKSPACES",
    "VerticalWorkflowService",
    "normalize_product_candidate",
    "parse_shopping_request",
]
