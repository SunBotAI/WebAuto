"""Governed composition and result verification for dynamic browser agents."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Protocol
from urllib.parse import urldefrag, urlparse
from uuid import uuid4

from webauto.agent_backends import (
    BrowserAgentBackend,
    BrowserAgentPolicyViolation,
    BrowserAgentSecurityPolicy,
    BrowserUseAdapter,
    BrowserUseInteractiveToolsFactory,
    BrowserUseModelBridge,
    BrowserWriteGrantAuthority,
    SensitiveDataRedactor,
)
from webauto.domain import (
    Action,
    AgentTaskBudget,
    AgentTaskRequest,
    AgentTaskResult,
    AgentTaskStatus,
    IdempotencyClass,
    Placement,
    RiskLevel,
    Run,
)
from webauto.runtime.browser import BrowserAgentSessionBridge

from .butler_service import (
    ButlerExecutionRequest,
    ButlerExecutionResult,
    ButlerIntent,
    ButlerService,
)
from .local_execution import LocalBrowserExecutionBackend
from .service import Actor, ApplicationService
from .settings import RuntimeConfigStore

_WRITE_CAPABILITIES = frozenset(
    {
        "web.file.upload",
        "web.complex_form.fill",
        "web.publish.submit",
        "web.purchase.submit",
        "web.message.send",
        "web.item.update",
        "web.item.delete",
    }
)
_WRITE_WORDS = (
    "发布",
    "上架",
    "改价",
    "下架",
    "删除",
    "退款",
    "下单",
    "支付",
    "发消息",
    "回复消息",
)
_DEFAULT_CRITERION = "Return a sourced result that directly addresses the objective"


class AgentResultVerifier(Protocol):
    async def verify(
        self, request: AgentTaskRequest, result: AgentTaskResult
    ) -> AgentTaskResult: ...


class EvidenceBasedAgentResultVerifier:
    """Verify a completed trace with a separate judge result and source checks."""

    async def verify(self, request: AgentTaskRequest, result: AgentTaskResult) -> AgentTaskResult:
        if result.status != AgentTaskStatus.COMPLETED:
            return result

        issues: list[str] = []
        if result.output.get("backend_validated") is not True:
            issues.append("independent judge did not validate the completed trace")
        if not str(result.output.get("final_result") or "").strip():
            issues.append("final result is empty")

        visited = {_canonical_url(url) for url in result.visited_urls if _canonical_url(url)}
        if not visited:
            issues.append("no visited page URL was recorded")
        for url in visited:
            if not _url_allowed(url, request):
                issues.append(f"visited URL is outside the approved domain scope: {url}")

        criteria = result.output.get("criteria")
        by_name = (
            {str(item.get("criterion") or ""): item for item in criteria if isinstance(item, dict)}
            if isinstance(criteria, list)
            else {}
        )
        for expected in request.success_criteria:
            evidence = by_name.get(expected)
            if not evidence:
                issues.append(f"success criterion has no evidence: {expected}")
                continue
            if evidence.get("satisfied") is not True:
                issues.append(f"success criterion was not satisfied: {expected}")
            evidence_urls = {
                _canonical_url(str(url))
                for url in evidence.get("evidence_urls", [])
                if _canonical_url(str(url))
            }
            if not evidence_urls:
                issues.append(f"success criterion has no source URL: {expected}")
            elif not evidence_urls <= visited:
                issues.append(f"success criterion references an unvisited URL: {expected}")

        for fact in result.facts:
            claim = str(fact.get("claim") or "").strip()
            source = _canonical_url(str(fact.get("source_url") or ""))
            if not claim or not source:
                issues.append("a reported fact is missing its claim or source URL")
            elif source not in visited:
                issues.append(f"a reported fact references an unvisited URL: {source}")

        values = result.model_dump(mode="python")
        if issues:
            values.update(
                status=AgentTaskStatus.UNCERTAIN,
                verified=False,
                uncertainties=list(dict.fromkeys([*result.uncertainties, *issues])),
                error="; ".join(issues),
            )
            return AgentTaskResult(**values)
        values.update(status=AgentTaskStatus.SUCCEEDED, verified=True, error=None)
        return AgentTaskResult(**values)


class BrowserAgentCoordinator:
    """Translate Butler requests into constrained dynamic-agent tasks."""

    def __init__(
        self,
        backend: BrowserAgentBackend,
        settings: RuntimeConfigStore,
        *,
        verifier: AgentResultVerifier | None = None,
        security_policy: BrowserAgentSecurityPolicy | None = None,
        redactor: SensitiveDataRedactor | None = None,
        application: ApplicationService | None = None,
    ) -> None:
        self._backend = backend
        self._settings = settings
        self._sessions = BrowserAgentSessionBridge(settings)
        self._verifier = verifier or EvidenceBasedAgentResultVerifier()
        self._security_policy = security_policy or BrowserAgentSecurityPolicy()
        self._redactor = redactor or SensitiveDataRedactor()
        self._application = application

    async def execute(self, request: ButlerExecutionRequest) -> ButlerExecutionResult:
        if self._requires_write_authority(request):
            return ButlerExecutionResult(
                "failed",
                error=(
                    "write-capable dynamic browser execution is not enabled in M1; "
                    "uploads, form submission, purchase, publish and store mutations remain blocked"
                ),
            )

        values = self._settings.load()
        agent_config = values["browser_agent"]
        domains = self._allowed_domains(request)
        unrestricted = domains == ("*",)
        if unrestricted and not agent_config.get("allow_unrestricted_domains", False):
            return ButlerExecutionResult(
                "failed",
                error=(
                    "this task has no explicit URL or domain scope; enable "
                    "browser_agent.allow_unrestricted_domains after reviewing the prompt-injection risk"
                ),
            )

        run = request.run
        profile_id = run.profile_id or "default"
        try:
            session = self._sessions.prepare(
                run_id=run.id,
                profile_id=profile_id,
                allowed_domains=domains,
            )
        except (RuntimeError, ValueError) as exc:
            return ButlerExecutionResult("failed", error=str(exc))
        if run.placement is not None and run.placement != session.placement:
            return ButlerExecutionResult(
                "failed",
                error=(
                    f"run placement {run.placement.value} does not match configured browser "
                    f"placement {session.placement.value}"
                ),
            )

        approval_probe = self._approval_probe_operation(request.message)
        task_context = {**request.context, "intent": request.intent.value}
        if approval_probe:
            task_context["approval_probe_operation"] = approval_probe
        task = AgentTaskRequest(
            run_id=run.id,
            objective=request.message,
            success_criteria=tuple(
                str(item).strip()
                for item in request.context.get("success_criteria", [_DEFAULT_CRITERION])
                if str(item).strip()
            ),
            profile_id=profile_id,
            placement=session.placement,
            allowed_domains=domains,
            allow_unrestricted_domains=unrestricted,
            context=task_context,
            read_only=True,
            max_risk=RiskLevel.L1,
            budget=AgentTaskBudget(
                max_steps=int(agent_config["max_steps"]),
                max_duration_seconds=float(agent_config["max_duration_seconds"]),
                max_external_writes=0,
            ),
        )
        try:
            self._security_policy.validate_request(task)
            result = await self._backend.run(task, session)
            result = await self._verifier.verify(task, result)
        except BrowserAgentPolicyViolation as exc:
            return ButlerExecutionResult(
                "failed",
                error=f"browser policy blocked the task: {self._redactor.redact_text(str(exc))}",
            )
        except Exception as exc:  # noqa: BLE001 - plugin boundary maps backend failures
            return ButlerExecutionResult(
                "failed",
                error=self._redactor.redact_text(f"{type(exc).__name__}: {exc}"),
            )
        payload = self._redactor.redact({"agent_result": result.model_dump(mode="json")})
        if result.status == AgentTaskStatus.SUCCEEDED:
            return ButlerExecutionResult("succeeded", payload)
        if result.status == AgentTaskStatus.WAITING_HUMAN:
            return ButlerExecutionResult("waiting_human", payload, result.error)
        if result.status == AgentTaskStatus.WAITING_APPROVAL:
            return ButlerExecutionResult("waiting_approval", payload, result.error)
        return ButlerExecutionResult("failed", payload, result.error or result.status.value)

    async def pause(self, run_id: str) -> None:
        await self._backend.pause(run_id)

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        await self._backend.resume(run_id, user_input)

    async def cancel(self, run_id: str) -> None:
        await self._backend.cancel(run_id)

    async def execute_governed_action(
        self,
        actor: Actor,
        run: Run,
        instruction: dict[str, object],
    ) -> ButlerExecutionResult:
        """Claim a consumed approval, then execute its one signed browser write."""
        if self._application is None:
            return ButlerExecutionResult(
                "failed", error="governed action approval verifier is unavailable"
            )
        operation = str(instruction.get("operation") or "")
        source_url = str(instruction.get("source_url") or "")
        object_scope = instruction.get("object_scope")
        approval_id = str(instruction.get("approval_id") or "")
        parsed = urlparse(source_url)
        if (
            not operation
            or not approval_id
            or not isinstance(object_scope, dict)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
        ):
            return ButlerExecutionResult("failed", error="governed action instruction is invalid")
        if object_scope.get("operation") != operation:
            return ButlerExecutionResult(
                "failed", error="governed operation differs from approved object"
            )
        if object_scope.get("source_url") != source_url:
            return ButlerExecutionResult(
                "failed", error="governed source URL differs from approved object"
            )
        try:
            action = Action.model_validate(instruction.get("action"))
            domains = tuple(str(value) for value in instruction.get("allowed_domains", []))
            approved_domains = tuple(
                str(value) for value in object_scope.get("allowed_domains", [])
            )
            if not domains or domains != approved_domains:
                raise RuntimeError("governed domain scope differs from approved object")
            files = tuple(
                Path(str(value)).resolve() for value in instruction.get("available_files", [])
            )
            actual_digests = sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in files)
            approved_digests = sorted(
                str(value.get("sha256"))
                for value in object_scope.get("files", [])
                if isinstance(value, dict)
            )
            if actual_digests != approved_digests:
                raise RuntimeError("governed files differ from approved object")
            approval = await self._application.claim_consumed_approval_execution(
                actor,
                approval_id,
                action=action,
                operation=operation,
                object_scope=object_scope,
            )
            if approval.run_id != run.id:
                raise RuntimeError("approval execution run binding does not match")
            session = self._sessions.prepare(
                run_id=run.id,
                profile_id=run.profile_id or "default",
                allowed_domains=domains,
            )
            grant = self._security_policy.write_grants.issue(
                run_id=run.id,
                operation=operation,
                object_digest=approval.object_digest,
                source_url=source_url,
                files=files,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return ButlerExecutionResult("failed", error=str(exc))
        values = self._settings.load()["browser_agent"]
        task = AgentTaskRequest(
            run_id=run.id,
            objective=str(
                instruction.get("objective")
                or f"Execute exactly one approved operation: {operation}"
            ),
            success_criteria=tuple(
                str(value)
                for value in instruction.get(
                    "success_criteria",
                    ["Verify the approved operation from page state"],
                )
            ),
            profile_id=run.profile_id or "default",
            placement=session.placement,
            allowed_domains=domains,
            allow_unrestricted_domains=False,
            prohibited_actions=("payment", "refund", "delete", "password", "verification"),
            available_files=files,
            context={
                "urls": [source_url],
                "intent": "governed_write",
                "approved_external_write": grant.model_dump(mode="json"),
                "approved_object": object_scope,
            },
            read_only=False,
            max_risk=action.risk_level,
            budget=AgentTaskBudget(
                max_steps=min(int(values["max_steps"]), 30),
                max_duration_seconds=min(float(values["max_duration_seconds"]), 600),
                max_external_writes=1,
            ),
        )
        try:
            self._security_policy.validate_request(task)
            result = await self._backend.run(task, session)
            write_observed = self._security_policy.write_grants.was_consumed(grant.id)
            if not write_observed:
                if result.status == AgentTaskStatus.WAITING_HUMAN:
                    payload = self._redactor.redact(
                        {"agent_result": result.model_dump(mode="json")}
                    )
                    return ButlerExecutionResult("waiting_human", payload, result.error)
                return ButlerExecutionResult(
                    "failed",
                    error=(
                        "approved external write was not observed at the "
                        "final tool boundary; a new approval is required"
                    ),
                )
            result = await self._verifier.verify(task, result)
            if (
                result.status != AgentTaskStatus.SUCCEEDED
                and action.idempotency == IdempotencyClass.NON_IDEMPOTENT
            ):
                criterion = (
                    "The approved operation is confirmed by current page "
                    "state or a business result query"
                )
                query_task = AgentTaskRequest(
                    run_id=run.id,
                    objective=(
                        "Do not repeat any write. Inspect the current page and "
                        f"determine whether {operation} already committed for "
                        f"this approved object: {object_scope}"
                    ),
                    success_criteria=(criterion,),
                    profile_id=run.profile_id or "default",
                    placement=session.placement,
                    allowed_domains=domains,
                    allow_unrestricted_domains=False,
                    available_files=(),
                    context={"intent": "commit_query"},
                    read_only=True,
                    max_risk=RiskLevel.L1,
                    budget=AgentTaskBudget(
                        max_steps=min(int(values["max_steps"]), 15),
                        max_duration_seconds=min(float(values["max_duration_seconds"]), 300),
                        max_external_writes=0,
                    ),
                )
                query_result = await self._backend.run(query_task, session)
                query_result = await self._verifier.verify(query_task, query_result)
                evidence = next(
                    (
                        value
                        for value in query_result.output.get("criteria", [])
                        if isinstance(value, dict) and value.get("criterion") == criterion
                    ),
                    None,
                )
                combined = self._redactor.redact(
                    {
                        "agent_result": result.model_dump(mode="json"),
                        "commit_query": query_result.model_dump(mode="json"),
                    }
                )
                if evidence and evidence.get("satisfied") is True:
                    return ButlerExecutionResult("succeeded", combined)
                if (
                    evidence
                    and evidence.get("satisfied") is False
                    and evidence.get("evidence_urls")
                ):
                    return ButlerExecutionResult(
                        "failed",
                        {
                            **combined,
                            "reapproval_required": True,
                            "commit_found": False,
                        },
                        "business query did not find the commit; a new approval is required",
                    )
                return ButlerExecutionResult(
                    "waiting_human",
                    {
                        **combined,
                        "uncertain_commit": True,
                        "automatic_retry_blocked": True,
                    },
                    "non-idempotent commit remains uncertain after a read-only query",
                )
        except BrowserAgentPolicyViolation as exc:
            return ButlerExecutionResult(
                "failed",
                error=f"browser policy blocked the approved action: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - plugin boundary
            return ButlerExecutionResult(
                "failed",
                error=self._redactor.redact_text(f"{type(exc).__name__}: {exc}"),
            )
        finally:
            self._security_policy.write_grants.revoke(grant.id)
        payload = self._redactor.redact({"agent_result": result.model_dump(mode="json")})
        if result.status == AgentTaskStatus.SUCCEEDED:
            return ButlerExecutionResult("succeeded", payload)
        if result.status == AgentTaskStatus.WAITING_HUMAN:
            return ButlerExecutionResult("waiting_human", payload, result.error)
        return ButlerExecutionResult("failed", payload, result.error or result.status.value)

    async def open_browser_session(
        self, profile_id: str, allowed_domains: tuple[str, ...]
    ) -> dict[str, object]:
        if "*" in allowed_domains and not self._settings.load()["browser_agent"].get(
            "allow_unrestricted_domains", False
        ):
            raise RuntimeError(
                "unrestricted browser session requires explicit configuration consent"
            )
        plan = self._sessions.prepare(
            run_id="session-" + uuid4().hex,
            profile_id=profile_id,
            allowed_domains=allowed_domains,
        )
        opener = getattr(self._backend, "open_session", None)
        if not callable(opener):
            raise TypeError("configured Browser Agent has no session lifecycle support")
        status = await opener(plan)
        return {**status, "placement": plan.placement.value}

    async def browser_session_status(self, profile_id: str) -> dict[str, object]:
        reader = getattr(self._backend, "session_status", None)
        if not callable(reader):
            raise TypeError("configured Browser Agent has no session lifecycle support")
        return reader(profile_id)

    async def close_browser_session(self, profile_id: str) -> dict[str, object]:
        closer = getattr(self._backend, "close_session", None)
        if not callable(closer):
            raise TypeError("configured Browser Agent has no session lifecycle support")
        return await closer(profile_id)

    @staticmethod
    def _approval_probe_operation(message: str) -> str | None:
        text = message.casefold()
        if any(
            marker in text for marker in ("加入购物车", "加购物车", "添加购物车", "add to cart")
        ):
            return "add_to_cart"
        if any(
            marker in text for marker in ("去结算", "进入结算", "立即购买", "buy now", "checkout")
        ):
            return "start_checkout"
        return None

    @staticmethod
    def _requires_write_authority(request: ButlerExecutionRequest) -> bool:
        if request.context.get("read_only"):
            return False
        if request.intent == ButlerIntent.XIANYU_PUBLISH:
            return True
        if request.context.get("allow_write") and (
            any(node.approval_required for node in request.graph.nodes)
            or any(node.capability in _WRITE_CAPABILITIES for node in request.graph.nodes)
        ):
            return True
        return any(word in request.message for word in _WRITE_WORDS)

    @staticmethod
    def _allowed_domains(request: ButlerExecutionRequest) -> tuple[str, ...]:
        explicit = request.context.get("allowed_domains")
        if isinstance(explicit, str):
            explicit = [explicit]
        if isinstance(explicit, (list, tuple, set)):
            domains = tuple(
                dict.fromkeys(str(item).strip() for item in explicit if str(item).strip())
            )
            if domains:
                return domains
        hosts: list[str] = []
        for raw_url in request.context.get("urls", []):
            hostname = urlparse(str(raw_url)).hostname
            if hostname and hostname not in hosts:
                hosts.append(hostname)
        return tuple(hosts) or ("*",)


def build_butler_service(
    application: ApplicationService,
    settings: RuntimeConfigStore,
) -> ButlerService:
    """Single composition root shared by Web, CLI and MCP."""

    values = settings.load()
    browser = values["browser"]
    agent = values["browser_agent"]
    placement = {
        "managed": Placement.DESKTOP_MANAGED,
        "cdp": Placement.BROWSER_ATTACH,
        "remote": Placement.REMOTE_DEDICATED,
    }[browser["mode"]]
    if agent["enabled"] and agent["backend"] == "browser_use":
        model_bridge = BrowserUseModelBridge()
        write_grants = BrowserWriteGrantAuthority()
        security_policy = BrowserAgentSecurityPolicy(write_grants)
        tools_factory = BrowserUseInteractiveToolsFactory(write_grants=write_grants)
        execution = BrowserAgentCoordinator(
            BrowserUseAdapter(
                model_factory=lambda: model_bridge.create(settings),
                controlled_tools_factory=tools_factory.create,
                security_policy=security_policy,
            ),
            settings,
            security_policy=security_policy,
            application=application,
        )
    else:
        execution = LocalBrowserExecutionBackend(settings)
    return ButlerService(
        application,
        execution,
        default_placement=placement,
    )


def _canonical_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return urldefrag(value)[0].rstrip("/")


def _url_allowed(url: str, request: AgentTaskRequest) -> bool:
    if request.allow_unrestricted_domains and "*" in request.allowed_domains:
        return True
    parsed = urlparse(url)
    host = parsed.hostname or ""
    origin = f"{parsed.scheme}://{host}"
    for pattern in request.allowed_domains:
        if "://" in pattern:
            scope = urlparse(pattern)
            same_origin = (
                parsed.scheme.lower() == scope.scheme.lower()
                and host.lower() == (scope.hostname or "").lower()
                and parsed.port == scope.port
            )
            scope_path = scope.path.rstrip("/")
            if same_origin and (
                not scope_path
                or parsed.path == scope_path
                or parsed.path.startswith(scope_path + "/")
            ):
                return True
        elif pattern.startswith("*."):
            root = pattern[2:]
            if host == root or host.endswith("." + root):
                return True
        elif fnmatch.fnmatch(host, pattern) or host == pattern or fnmatch.fnmatch(origin, pattern):
            return True
    return False
