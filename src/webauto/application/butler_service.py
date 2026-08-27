"""Personal-butler orchestration from conversation to an execution backend."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from webauto.domain import CapabilityGraph, ConversationRole, Placement, Run
from webauto.scenarios import ListingPublishPack, ShoppingPack

from .butler import ChatReply
from .service import Actor, ApplicationService, PermissionDenied, Role
from .vertical_workflows import (
    SHOPPING_WORKSPACES,
    VerticalWorkflowService,
)


class ButlerIntent(str, Enum):
    WEB = "web"
    SHOPPING = "shopping"
    XIANYU_BUY = "xianyu_buy"
    XIANYU_PUBLISH = "xianyu_publish"
    XIANYU_MANAGE = "xianyu_manage"


@dataclass(frozen=True, slots=True)
class ButlerExecutionRequest:
    run: Run
    intent: ButlerIntent
    graph: CapabilityGraph
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ButlerExecutionResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ButlerExecutionBackend(Protocol):
    async def execute(self, request: ButlerExecutionRequest) -> ButlerExecutionResult: ...


def _same_product_page(current_url: str, product_url: str, item_id: str) -> bool:
    current = urlparse(current_url)
    product = urlparse(product_url)
    if (
        current.scheme not in {"http", "https"}
        or product.scheme not in {"http", "https"}
        or not current.hostname
        or current.hostname.casefold() != (product.hostname or "").casefold()
    ):
        return False

    def identities(parsed: Any) -> set[str]:
        values = {
            unquote(value).casefold()
            for key, items in parse_qs(parsed.query).items()
            if key.casefold() in {"id", "itemid", "item_id", "sku", "skuid"}
            for value in items
        }
        segment = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1]).strip().casefold()
        stem = segment.rsplit(".", 1)[0]
        if stem and stem not in {"item", "product", "detail", "index"}:
            values.add(segment)
            values.add(stem)
        return values

    expected_id = item_id.strip().casefold()
    current_ids = identities(current)
    if expected_id and expected_id in current_ids:
        return True
    product_ids = identities(product)
    if product_ids or current_ids:
        return bool(product_ids & current_ids)
    return current.path.rstrip("/") == product.path.rstrip("/")


class IntentRouter:
    """Conservative deterministic routing; a model router can implement the same boundary."""

    def classify(self, message: str) -> ButlerIntent:
        text = message.lower()
        xianyu = "咸鱼" in text or "闲鱼" in text
        if xianyu and any(word in text for word in ("发布", "上架", "卖掉", "草稿")):
            return ButlerIntent.XIANYU_PUBLISH
        if xianyu and any(
            word in text for word in ("店铺", "消息", "订单", "商品管理", "改价", "下架")
        ):
            return ButlerIntent.XIANYU_MANAGE
        if xianyu and any(word in text for word in ("买", "找", "搜", "看", "比较", "咨询")):
            return ButlerIntent.XIANYU_BUY
        if any(word in text for word in ("买", "购物", "商品", "比价", "价格", "淘宝", "京东")):
            return ButlerIntent.SHOPPING
        return ButlerIntent.WEB

    @staticmethod
    def context(message: str) -> dict[str, Any]:
        urls = re.findall(r"https?://[^\s<>]+", message)
        budget = re.search(r"(?:预算|不超过|以内)\s*(\d+(?:\.\d+)?)", message)
        return {
            "urls": urls,
            "budget": float(budget.group(1)) if budget else None,
            "read_only": any(
                word in message for word in ("只看", "不要买", "不要发布", "只生成草稿")
            ),
        }

    @staticmethod
    def is_contextual_follow_up(message: str) -> bool:
        text = message.strip().lower()
        if re.search(r"https?://", text):
            return False
        explicit = (
            "淘宝",
            "京东",
            "咸鱼",
            "闲鱼",
            "购物",
            "发布",
            "上架",
            "店铺",
            "下单",
            "支付",
            "表单",
            "上传",
        )
        return not any(marker in text for marker in explicit)


class ButlerService:
    def __init__(
        self,
        application: ApplicationService,
        execution: ButlerExecutionBackend,
        *,
        router: IntentRouter | None = None,
        default_profile_id: str = "default",
        default_placement: Placement = Placement.DESKTOP_MANAGED,
    ) -> None:
        self._application = application
        self._execution = execution
        self._router = router or IntentRouter()
        self._profile_id = default_profile_id
        self._placement = default_placement
        self._verticals = VerticalWorkflowService(application)

    async def handle(
        self,
        actor: Actor,
        message: str,
        *,
        conversation_id: str | None = None,
    ) -> ChatReply:
        message = message.strip()
        if not message:
            return ChatReply(
                "clarification",
                "请告诉我需要浏览、购买、发布或管理什么。",
                {"questions": ["要处理什么对象？"]},
            )

        if conversation_id:
            conversation = await self._application.get_conversation(actor, conversation_id)
        else:
            conversation = await self._application.create_conversation(actor, title=message[:160])
        previous = conversation
        conversation = await self._application.append_conversation_message(
            actor,
            conversation.id,
            role=ConversationRole.USER,
            content=message,
        )

        async def reply(
            kind: str,
            text: str,
            payload: dict[str, Any],
            *,
            run_id: str | None = None,
        ) -> ChatReply:
            complete_payload = {"conversation_id": conversation.id, **payload}
            await self._application.append_conversation_message(
                actor,
                conversation.id,
                role=ConversationRole.ASSISTANT,
                content=text,
                kind=kind,
                run_id=run_id,
                metadata={"run_id": run_id} if run_id else {},
            )
            return ChatReply(kind, text, complete_payload)

        if message in {"帮我弄一下", "帮我处理", "处理一下", "搞一下"}:
            return await reply(
                "clarification",
                "请告诉我需要浏览、购买、发布或管理什么，以及哪些操作不能自动执行。",
                {"questions": ["要处理什么对象？", "只查看、生成草稿，还是允许写操作？"]},
            )

        intent = self._router.classify(message)
        if (
            conversation_id
            and intent == ButlerIntent.WEB
            and previous.last_intent
            and self._router.is_contextual_follow_up(message)
        ):
            try:
                intent = ButlerIntent(previous.last_intent)
            except ValueError:
                pass

        context = self._router.context(message)
        previous_context = dict(previous.context)
        if not context["urls"] and previous_context.get("urls"):
            context["urls"] = list(previous_context["urls"])
        if context["budget"] is None and previous_context.get("budget") is not None:
            context["budget"] = previous_context["budget"]
        context["read_only"] = bool(context["read_only"] or previous_context.get("read_only"))
        if previous_context.get("allowed_domains"):
            context["allowed_domains"] = list(previous_context["allowed_domains"])
        context["conversation_id"] = conversation.id
        context["owner_id"] = actor.user_id
        context["conversation_history"] = [
            {"role": item.role.value, "content": item.content}
            for item in conversation.messages[:-1]
            if item.role == ConversationRole.USER
        ][-8:]
        persisted_context = {
            key: value
            for key, value in context.items()
            if key not in {"conversation_history", "owner_id"}
        }
        await self._application.update_conversation_context(
            actor,
            conversation.id,
            last_intent=intent.value,
            context=persisted_context,
        )

        graph = self._graph(intent)
        goal = await self._application.create_goal(
            actor,
            objective=message,
            success_criteria=["执行结果已由页面状态或业务查询验证"],
            constraints={"intent": intent.value, **persisted_context},
        )
        plan_id = "butler-" + uuid4().hex
        run = await self._application.create_run(
            actor,
            goal_id=goal.id,
            plan_id=plan_id,
            placement=self._placement,
            profile_id=self._profile_id,
        )
        await self._application.set_plan_view(
            actor,
            run.id,
            candidates=[
                {
                    "id": plan_id,
                    "intent": intent.value,
                    "capabilities": [node.capability for node in graph.nodes],
                    "placement": self._placement.value,
                }
            ],
            selection_reason="个人管家场景路由；关键写操作仍由审批策略约束",
        )
        run = await self._application.start_run(actor, run.id)
        try:
            result = await self._execution.execute(
                ButlerExecutionRequest(run, intent, graph, message, context)
            )
        except Exception as exc:  # noqa: BLE001 - execution plugin boundary
            result = ButlerExecutionResult(
                "failed",
                error=f"execution backend failed: {type(exc).__name__}: {exc}",
            )
        if result.status == "succeeded" and intent != ButlerIntent.WEB:
            try:
                vertical_output = await self._verticals.process_agent_result(
                    actor,
                    run_id=run.id,
                    intent=intent.value,
                    message=message,
                    output=result.output,
                )
            except Exception as exc:  # noqa: BLE001 - result enrichment boundary
                vertical_output = {
                    **result.output,
                    "vertical_processing_error": f"{type(exc).__name__}: {exc}",
                }
            result = ButlerExecutionResult(result.status, vertical_output, result.error)
        if result.status == "succeeded" and intent != ButlerIntent.WEB:
            persisted_context = await self._remember_vertical_workspaces(
                actor,
                conversation.id,
                intent,
                persisted_context,
                result.output,
            )
        bound_action = None
        if result.status == "waiting_approval":
            try:
                bound_action = await self._bind_low_risk_browser_approval(
                    actor,
                    message=message,
                    context={**previous_context, **persisted_context},
                    output=result.output,
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                bound_action = None
        if bound_action is not None:
            result = ButlerExecutionResult(
                result.status,
                {**result.output, "governed_action": bound_action},
                result.error,
            )
        await self._application.set_run_result(
            actor,
            run.id,
            {
                "status": result.status,
                "output": result.output,
                "error": result.error,
            },
        )
        if bound_action is not None:
            read_final = await self._application.finish_run(actor, run.id, succeeded=True)
            return await reply(
                "approval_required",
                "已经在真实关键按钮前停止，并生成了绑定候选、页面和按钮的审批预览。",
                {
                    "run_id": bound_action["action_run_id"],
                    "read_run_id": read_final.id,
                    "approval_id": bound_action["approval_id"],
                    "governed_action": bound_action,
                },
                run_id=bound_action["action_run_id"],
            )
        if result.status == "succeeded":
            final = await self._application.finish_run(actor, run.id, succeeded=True)
            return await reply(
                "completed",
                "任务已经执行并验证。",
                {"run_id": final.id, "result": result.output},
                run_id=final.id,
            )
        if result.status == "waiting_human":
            final = await self._application.takeover(actor, run.id)
            return await reply(
                "human_takeover",
                "浏览器遇到登录或安全验证，已经停止自动重试，请你接管。",
                {"run_id": final.id, **result.output},
                run_id=final.id,
            )
        if result.status == "waiting_approval":
            final = await self._application.wait_for_approval(actor, run.id)
            return await reply(
                "approval_required",
                "执行到关键操作，等待你的审批。",
                {"run_id": final.id, **result.output},
                run_id=final.id,
            )
        final = await self._application.finish_run(actor, run.id, succeeded=False)
        return await reply(
            "failed",
            "任务未能完成，已停止且没有把失败步骤当成成功。",
            {"run_id": final.id, "error": result.error, "result": result.output},
            run_id=final.id,
        )

    async def _remember_vertical_workspaces(
        self,
        actor: Actor,
        conversation_id: str,
        intent: ButlerIntent,
        context: dict[str, Any],
        output: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(context)
        shopping = output.get("shopping_workspace")
        if isinstance(shopping, dict):
            updated["shopping_workspace_id"] = shopping["id"]
            recommended = shopping.get("result_card", {}).get("recommended_key")
            if recommended:
                updated["selected_candidate_key"] = recommended
                ranked = shopping.get("result_card", {}).get("ranked", [])
                selected = next(
                    (item for item in ranked if item.get("key") == recommended),
                    None,
                )
                if selected:
                    product_url = str(selected["product"]["url"])
                    host = urlparse(product_url).hostname
                    updated["urls"] = [product_url]
                    if host:
                        updated["allowed_domains"] = [host]
        xianyu_buy = output.get("xianyu_buy_workspace")
        if isinstance(xianyu_buy, dict):
            updated["xianyu_buy_workspace_id"] = xianyu_buy["id"]
        store = output.get("xianyu_store_workspace")
        if isinstance(store, dict):
            updated["xianyu_store_workspace_id"] = store["id"]
        await self._application.update_conversation_context(
            actor,
            conversation_id,
            last_intent=intent.value,
            context=updated,
        )
        return updated

    async def _bind_low_risk_browser_approval(
        self,
        actor: Actor,
        *,
        message: str,
        context: dict[str, Any],
        output: dict[str, Any],
    ) -> dict[str, Any] | None:
        agent = output.get("agent_result")
        agent_output = agent.get("output") if isinstance(agent, dict) else None
        request = agent_output.get("approval_request") if isinstance(agent_output, dict) else None
        if not isinstance(request, dict):
            return None
        operation = str(request.get("operation") or "")
        if operation not in {"add_to_cart", "start_checkout"}:
            return None
        workspace_id = str(context.get("shopping_workspace_id") or "")
        if not workspace_id:
            return None
        workspace = await self._verticals.get_workspace(actor, SHOPPING_WORKSPACES, workspace_id)
        key = str(
            context.get("selected_candidate_key")
            or workspace.get("result_card", {}).get("recommended_key")
            or ""
        )
        if not key:
            return None
        ranked = workspace.get("result_card", {}).get("ranked", [])
        selected = next((item for item in ranked if item.get("key") == key), None)
        product = selected.get("product") if isinstance(selected, dict) else None
        if not isinstance(product, dict):
            return None
        quantity_match = re.search(r"(\d+)\s*(?:件|个|台|份|套)", message)
        current_url = str(request.get("current_url") or "")
        host = urlparse(current_url).hostname
        if not host or not _same_product_page(
            current_url,
            str(product.get("url") or ""),
            str(product.get("item_id") or ""),
        ):
            return None
        button_text = str(request.get("button_text") or "").strip()
        if not button_text:
            return None
        return await self._verticals.prepare_action(
            actor,
            workspace_category=SHOPPING_WORKSPACES,
            workspace_id=workspace_id,
            operation=operation,
            object_scope={
                "candidate_key": key,
                "quantity": int(quantity_match.group(1)) if quantity_match else 1,
                "address_masked": "未在本次只读预览中提供",
            },
            preview={
                "candidate_key": key,
                "button_text": button_text,
                "target": request.get("target", {}),
            },
            page_revision=str(request.get("page_revision") or ""),
            evidence_ids=[str(value) for value in request.get("evidence_ids", []) if str(value)],
            source_url=current_url,
            allowed_domains=[host],
        )

    def supports_governed_actions(self) -> bool:
        return callable(getattr(self._execution, "execute_governed_action", None))

    async def execute_governed_action(
        self,
        actor: Actor,
        instruction: dict[str, object],
    ) -> dict[str, object]:
        self._require_browser_operator(actor)
        handler = getattr(self._execution, "execute_governed_action", None)
        if not callable(handler):
            raise TypeError("dynamic Browser Agent governed writes are not enabled")
        run_id = str(instruction.get("action_run_id") or "")
        run = await self._application.get_run(actor, run_id)
        result = await handler(actor, run, instruction)
        await self._application.set_run_result(
            actor,
            run.id,
            {
                "status": result.status,
                "output": result.output,
                "error": result.error,
            },
        )
        if result.status == "succeeded":
            final = await self._application.finish_run(actor, run.id, succeeded=True)
        elif result.status == "waiting_human":
            final = await self._application.takeover(actor, run.id)
        else:
            final = await self._application.finish_run(actor, run.id, succeeded=False)
        return {
            "run": final,
            "status": result.status,
            "output": result.output,
            "error": result.error,
        }

    async def pause(self, actor: Actor, run_id: str) -> Run:
        await self._control_backend("pause", run_id)
        return await self._application.pause_run(actor, run_id)

    async def resume(self, actor: Actor, run_id: str, *, user_input: str | None = None) -> Run:
        updated = await self._application.resume_run(actor, run_id)
        try:
            await self._control_backend("resume", run_id, user_input)
        except Exception:
            await self._application.pause_run(actor, run_id)
            raise
        return updated

    async def cancel(self, actor: Actor, run_id: str) -> Run:
        await self._control_backend("cancel", run_id)
        return await self._application.cancel_run(actor, run_id)

    async def takeover(self, actor: Actor, run_id: str) -> Run:
        await self._control_backend("pause", run_id)
        return await self._application.takeover(actor, run_id)

    async def return_control(
        self, actor: Actor, run_id: str, *, user_input: str | None = None
    ) -> Run:
        updated = await self._application.return_control(actor, run_id)
        try:
            await self._control_backend("resume", run_id, user_input)
        except Exception:
            await self._application.takeover(actor, run_id)
            raise
        return updated

    async def _control_backend(self, operation: str, *arguments: Any) -> None:
        handler = getattr(self._execution, operation, None)
        if handler is not None:
            await handler(*arguments)

    async def open_browser_session(
        self,
        actor: Actor,
        *,
        profile_id: str = "default",
        allowed_domains: tuple[str, ...] = ("*",),
    ) -> dict[str, object]:
        self._require_browser_operator(actor)
        handler = getattr(self._execution, "open_browser_session", None)
        if not callable(handler):
            raise TypeError("dynamic Browser Agent is not enabled")
        return await handler(profile_id, allowed_domains)

    async def browser_session_status(
        self, actor: Actor, *, profile_id: str = "default"
    ) -> dict[str, object]:
        self._require_browser_operator(actor)
        handler = getattr(self._execution, "browser_session_status", None)
        if not callable(handler):
            raise TypeError("dynamic Browser Agent is not enabled")
        return await handler(profile_id)

    async def close_browser_session(
        self, actor: Actor, *, profile_id: str = "default"
    ) -> dict[str, object]:
        self._require_browser_operator(actor)
        handler = getattr(self._execution, "close_browser_session", None)
        if not callable(handler):
            raise TypeError("dynamic Browser Agent is not enabled")
        return await handler(profile_id)

    @staticmethod
    def _require_browser_operator(actor: Actor) -> None:
        if Role.ADMIN not in actor.roles and Role.OPERATOR not in actor.roles:
            raise PermissionDenied("role operator is required")

    @staticmethod
    def _graph(intent: ButlerIntent) -> CapabilityGraph:
        if intent == ButlerIntent.XIANYU_PUBLISH:
            return ListingPublishPack().graph
        shopping = ShoppingPack().graph
        if intent in {ButlerIntent.SHOPPING, ButlerIntent.XIANYU_BUY}:
            return shopping
        capability = "web.store.inspect" if intent == ButlerIntent.XIANYU_MANAGE else "web.browse"
        node = shopping.nodes[0].model_copy(update={"capability": capability})
        return shopping.model_copy(update={"nodes": [node], "edges": [], "entry_node_id": node.id})
