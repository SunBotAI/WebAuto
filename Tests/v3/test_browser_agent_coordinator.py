"""Browser Agent coordination, verification, composition and UI tests."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from webauto.agent_backends import BrowserUseReadOnlyToolsFactory
from webauto.application.browser_agent import (
    BrowserAgentCoordinator,
    EvidenceBasedAgentResultVerifier,
    build_butler_service,
)
from webauto.application.butler_service import (
    ButlerExecutionRequest,
    ButlerIntent,
)
from webauto.application.dashboard import DASHBOARD_HTML
from webauto.application.local_execution import LocalBrowserExecutionBackend
from webauto.application.service import ApplicationService
from webauto.application.settings import RuntimeConfigStore
from webauto.domain import (
    AgentTaskRequest,
    AgentTaskResult,
    AgentTaskStatus,
    Placement,
    RiskLevel,
    Run,
)
from webauto.scenarios import ListingPublishPack, ShoppingPack


def agent_request(**updates) -> AgentTaskRequest:
    values = {
        "run_id": "run-1",
        "objective": "Research the requested topic",
        "success_criteria": ("Return a sourced answer",),
        "profile_id": "personal",
        "placement": Placement.BROWSER_ATTACH,
        "allowed_domains": ("example.test",),
        "read_only": True,
        "max_risk": RiskLevel.L1,
    }
    values.update(updates)
    return AgentTaskRequest(**values)


def completed_result(request: AgentTaskRequest, *, judged: bool) -> AgentTaskResult:
    url = "https://example.test/result"
    return AgentTaskResult(
        status=AgentTaskStatus.COMPLETED,
        output={
            "final_result": "A sourced answer",
            "backend_validated": judged,
            "criteria": [
                {
                    "criterion": request.success_criteria[0],
                    "satisfied": True,
                    "evidence_urls": [url],
                    "explanation": "The result page contains the answer.",
                }
            ],
        },
        facts=[{"claim": "The answer is supported.", "source_url": url}],
        visited_urls=[url],
        evidence_ids=[url],
    )


@pytest.mark.asyncio
async def test_evidence_verifier_rejects_self_claim_and_accepts_judged_evidence() -> None:
    verifier = EvidenceBasedAgentResultVerifier()
    request = agent_request()

    uncertain = await verifier.verify(request, completed_result(request, judged=False))
    assert uncertain.status == AgentTaskStatus.UNCERTAIN
    assert uncertain.verified is False
    assert "independent judge" in (uncertain.error or "")

    verified = await verifier.verify(request, completed_result(request, judged=True))
    assert verified.status == AgentTaskStatus.SUCCEEDED
    assert verified.verified is True


@pytest.mark.asyncio
async def test_evidence_verifier_rejects_full_url_prefix_domain_confusion() -> None:
    verifier = EvidenceBasedAgentResultVerifier()
    request = agent_request(allowed_domains=("https://example.test",))
    evil_url = "https://example.test.evil/result"
    claimed = completed_result(request, judged=True)
    criteria = list(claimed.output["criteria"])
    criteria[0] = {**criteria[0], "evidence_urls": [evil_url]}
    claimed = AgentTaskResult(
        **{
            **claimed.model_dump(mode="python"),
            "output": {**claimed.output, "criteria": criteria},
            "facts": [{"claim": "Untrusted claim", "source_url": evil_url}],
            "visited_urls": [evil_url],
            "evidence_ids": [evil_url],
        }
    )

    result = await verifier.verify(request, claimed)

    assert result.status == AgentTaskStatus.UNCERTAIN
    assert "outside the approved domain scope" in (result.error or "")


class _CompletingBackend:
    name = "fake-agent"

    def __init__(self) -> None:
        self.requests: list[AgentTaskRequest] = []

    async def run(self, request, session):
        self.requests.append(request)
        return completed_result(
            request.model_copy(update={"allowed_domains": ("example.test",)}), judged=True
        )

    async def pause(self, run_id: str) -> None:
        return None

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        return None

    async def cancel(self, run_id: str) -> None:
        return None


def butler_request(*, publish: bool = False) -> ButlerExecutionRequest:
    return ButlerExecutionRequest(
        run=Run(
            id="run-1",
            goal_id="goal-1",
            plan_id="plan-1",
            profile_id="personal",
            placement=Placement.BROWSER_ATTACH,
        ),
        intent=ButlerIntent.XIANYU_PUBLISH if publish else ButlerIntent.WEB,
        graph=ListingPublishPack().graph if publish else ShoppingPack().graph,
        message="Research the requested topic",
        context={},
    )


@pytest.mark.asyncio
async def test_coordinator_allows_no_url_only_after_explicit_global_web_consent(
    tmp_path: Path,
) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {
            "browser": {"mode": "cdp", "cdp_endpoint": "http://127.0.0.1:9222"},
            "browser_agent": {"allow_unrestricted_domains": True},
        },
        {},
    )
    backend = _CompletingBackend()
    coordinator = BrowserAgentCoordinator(backend, store)

    result = await coordinator.execute(butler_request())

    assert result.status == "succeeded"
    assert backend.requests[0].allowed_domains == ("*",)
    assert backend.requests[0].allow_unrestricted_domains is True


@pytest.mark.asyncio
async def test_coordinator_blocks_no_url_without_global_web_consent(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {"browser": {"mode": "cdp", "cdp_endpoint": "http://127.0.0.1:9222"}},
        {},
    )
    backend = _CompletingBackend()

    result = await BrowserAgentCoordinator(backend, store).execute(butler_request())

    assert result.status == "failed"
    assert "allow_unrestricted_domains" in (result.error or "")
    assert backend.requests == []


@pytest.mark.asyncio
async def test_coordinator_does_not_send_write_graph_to_read_only_agent(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update({"browser_agent": {"allow_unrestricted_domains": True}}, {})
    backend = _CompletingBackend()

    result = await BrowserAgentCoordinator(backend, store).execute(butler_request(publish=True))

    assert result.status == "failed"
    assert "write-capable" in (result.error or "")
    assert backend.requests == []


class _FakeRegistry:
    def __init__(self) -> None:
        self.registry = SimpleNamespace(
            actions={
                name: object()
                for name in (
                    "done",
                    "search",
                    "navigate",
                    "extract",
                    "scroll",
                    "click",
                    "input",
                    "upload_file",
                    "evaluate",
                    "evil_shell",
                )
            }
        )


class _FakeTools:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.registry = _FakeRegistry()

    def exclude_action(self, name: str) -> None:
        self.registry.registry.actions.pop(name, None)


def test_read_only_tools_factory_uses_strict_allowlist() -> None:
    factory = BrowserUseReadOnlyToolsFactory(
        module_loader=lambda: SimpleNamespace(Tools=_FakeTools)
    )

    tools = factory.create()

    assert set(tools.registry.registry.actions) == {
        "done",
        "search",
        "navigate",
        "extract",
        "scroll",
    }
    assert tools.kwargs["display_files_in_done_text"] is False


def test_composition_defaults_local_and_builds_agent_only_when_explicitly_enabled(
    tmp_path: Path,
) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    service = ApplicationService()
    local = build_butler_service(service, store)
    assert isinstance(local._execution, LocalBrowserExecutionBackend)
    assert store.test_connections()["browser_agent"]["ok"] is True

    store.update(
        {
            "browser": {"mode": "cdp"},
            "browser_agent": {
                "backend": "browser_use",
                "enabled": True,
                "allow_unrestricted_domains": True,
            },
        },
        {},
    )
    dynamic = build_butler_service(service, store)
    assert isinstance(dynamic._execution, BrowserAgentCoordinator)
    assert dynamic._placement == Placement.BROWSER_ATTACH


def test_dashboard_exposes_browser_agent_safety_settings() -> None:
    for element_id in (
        "cfg-agent-enabled",
        "cfg-agent-backend",
        "cfg-agent-max-steps",
        "cfg-agent-max-duration",
        "cfg-agent-unrestricted-domains",
    ):
        assert f'id="{element_id}"' in DASHBOARD_HTML
    assert "allow_unrestricted_domains" in DASHBOARD_HTML
