"""Local Chrome/CDP execution backend for personal-butler read workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from webauto.agent import GraphExecutor, StateVerifier, StepOutcome
from webauto.application.settings import RuntimeConfigStore
from webauto.domain import (
    Action,
    ActionKind,
    ActionStatus,
    IdempotencyClass,
    RiskLevel,
    VerifierSpec,
)
from webauto.runtime.artifacts import LocalArtifactStore
from webauto.runtime.browser import (
    ActionExecutor,
    BrowserControl,
    BrowserObserver,
    ControlOwner,
    DetectionSurfaceProbe,
    InMemoryLeaseManager,
    ProfileIdentityStore,
    SiteRateLimiter,
    SiteRatePolicy,
    compare_identity,
    configured_browser,
)

from .butler_service import ButlerExecutionRequest, ButlerExecutionResult


class LocalBrowserExecutionBackend:
    """Execute read-only graph steps in a configured local browser with evidence."""

    def __init__(self, settings: RuntimeConfigStore) -> None:
        self._settings = settings
        self._leases = InMemoryLeaseManager()
        self._rate_limiter = SiteRateLimiter(SiteRatePolicy())

    async def execute(self, request: ButlerExecutionRequest) -> ButlerExecutionResult:
        if not request.context.get("urls"):
            return ButlerExecutionResult(
                "failed",
                error="当前真实浏览器后端需要用户提供页面 URL；站内搜索由后续 Site Skill 接入",
            )
        configured = configured_browser(self._settings)
        run, provider = request.run, configured.provider
        profile_id = run.profile_id or "default"
        lease = await self._leases.acquire(
            profile_id, run.id, run.placement or provider.capabilities.placement, ttl_seconds=300
        )
        control = BrowserControl()
        await control.acquire(ControlOwner.AGENT)
        try:
            session = (
                await provider.connect(configured.endpoint, profile_id)
                if configured.mode == "cdp" and configured.endpoint
                else await provider.start(profile_id)
            )
            settings = self._settings.load()
            probe = await DetectionSurfaceProbe().inspect(
                session.active_page, browser_family="chrome", browser_version="unknown"
            )
            identity_store = ProfileIdentityStore(self._settings.runtime_dir / "identities")
            baseline = identity_store.load(profile_id)
            if baseline is None:
                identity_store.save_once(profile_id, probe.identity)
            else:
                drift = compare_identity(baseline, probe.identity)
                if not drift.compatible:
                    return ButlerExecutionResult("failed", error=drift.summary)
            session.metadata["detection_surface"] = {
                "webdriver_exposed": probe.webdriver_exposed,
                "warnings": list(probe.warnings),
            }
            artifacts = LocalArtifactStore(Path(settings["storage"]["artifacts_dir"]))
            state_verifier = StateVerifier()

            async def verify(action, state):
                return await state_verifier.verify(action.verifier, state)

            actions = ActionExecutor(
                observer=BrowserObserver(artifacts),
                verifier=verify,
                control=control,
                rate_limiter=self._rate_limiter,
            )

            async def browse(node, context: dict[str, Any]) -> StepOutcome:
                url = str(context["urls"][0])
                parsed = urlparse(url)
                action = Action(
                    kind=ActionKind.NAVIGATE,
                    arguments={"url": url},
                    preconditions=["user supplied or approved URL"],
                    expected_effect={"url_contains": parsed.netloc},
                    risk_level=RiskLevel.L0,
                    idempotency=IdempotencyClass.READ_ONLY,
                    verifier=VerifierSpec(
                        kind="page_state", expectation={"url_contains": parsed.netloc}
                    ),
                )
                result = await actions.execute(action, session)
                return StepOutcome(
                    succeeded=result.status == ActionStatus.SUCCEEDED,
                    output={"url": url, "evidence_ids": result.evidence_ids, **result.output},
                    error=result.error_message,
                )

            async def extract(node, context: dict[str, Any]) -> StepOutcome:
                action = Action(
                    kind=ActionKind.EXTRACT,
                    target={"selector": "body"},
                    preconditions=["page navigation verified"],
                    expected_effect={"content_extracted": True},
                    risk_level=RiskLevel.L0,
                    idempotency=IdempotencyClass.READ_ONLY,
                    verifier=VerifierSpec(kind="page_state", expectation={"dom_nonempty": True}),
                )
                result = await actions.execute(action, session)
                text = str(result.output.get("text") or "").strip()
                return StepOutcome(
                    succeeded=result.status == ActionStatus.SUCCEEDED and bool(text),
                    output={"text": text[:20000], "evidence_ids": result.evidence_ids},
                    error=None if text else "page body is empty",
                )

            async def normalize(node, context: dict[str, Any]) -> StepOutcome:
                extracted = next(
                    (
                        value
                        for value in context.get("step_outputs", {}).values()
                        if "text" in value
                    ),
                    {},
                )
                return StepOutcome(output={"normalized_text": extracted.get("text", "")})

            async def compare(node, context: dict[str, Any]) -> StepOutcome:
                return StepOutcome(output={"status": "page captured for comparison"})

            handlers = {
                "web.browse": browse,
                "web.list.extract": extract,
                "web.normalize": normalize,
                "web.compare": compare,
                "web.store.inspect": browse,
            }
            context = dict(request.context)

            async def handler_with_outputs(node, ctx):
                outcome = await handlers[node.capability](node, ctx)
                ctx.setdefault("step_outputs", {})[node.id] = outcome.output
                return outcome

            executor = GraphExecutor({name: handler_with_outputs for name in handlers})
            result = await executor.run(run.id, request.graph, context)
            challenge = next(
                (value for value in result.outputs.values() if value.get("challenge")), None
            )
            return ButlerExecutionResult(
                "waiting_human" if challenge else ("succeeded" if result.succeeded else "failed"),
                {
                    "outputs": result.outputs,
                    "events": [event.model_dump(mode="json") for event in result.events],
                },
                None if result.succeeded else f"step failed: {result.failed_node_id}",
            )
        except Exception as exc:  # noqa: BLE001 - local browser backend boundary
            return ButlerExecutionResult("failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            await control.release(ControlOwner.AGENT)
            await provider.close()
            await self._leases.release(lease)
