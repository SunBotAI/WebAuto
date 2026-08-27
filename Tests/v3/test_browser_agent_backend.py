"""M1 Browser Agent contracts, configuration and optional Browser Use adapter tests."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from webauto.agent_backends import (
    BrowserAgentPolicyNotReady,
    BrowserUseAdapter,
    BrowserUseModelBridge,
)
from webauto.application.settings import RuntimeConfigStore
from webauto.domain import (
    AgentTaskBudget,
    AgentTaskRequest,
    AgentTaskResult,
    AgentTaskStatus,
    Placement,
    RiskLevel,
)
from webauto.runtime.browser import BrowserAgentSessionBridge


def task_request(**updates) -> AgentTaskRequest:
    values = {
        "run_id": "run-1",
        "objective": "Search the approved site and summarize the result",
        "success_criteria": ["A sourced result is returned"],
        "profile_id": "personal",
        "placement": Placement.DESKTOP_MANAGED,
        "allowed_domains": ["example.test"],
        "read_only": True,
        "max_risk": RiskLevel.L1,
        "budget": AgentTaskBudget(max_steps=12, max_duration_seconds=120),
    }
    values.update(updates)
    return AgentTaskRequest(**values)


def test_agent_task_contract_requires_explicit_unrestricted_domain_consent() -> None:
    with pytest.raises(ValidationError, match="allow_unrestricted_domains"):
        task_request(allowed_domains=["*"])

    request = task_request(allowed_domains=["*"], allow_unrestricted_domains=True)
    assert request.allowed_domains == ("*",)
    assert request.budget.max_external_writes == 0

    with pytest.raises(ValidationError, match="wildcard domain scopes"):
        task_request(allowed_domains=["exam*ple.test"])

    exact_url = task_request(allowed_domains=["https://example.test/catalog"])
    assert exact_url.allowed_domains == ("https://example.test/catalog",)


def test_agent_task_contract_never_accepts_unverified_success() -> None:
    with pytest.raises(ValidationError, match="verified"):
        AgentTaskResult(status=AgentTaskStatus.SUCCEEDED, verified=False)

    completed = AgentTaskResult(
        status=AgentTaskStatus.COMPLETED,
        verified=False,
        output={"summary": "agent claims completion"},
    )
    assert completed.requires_verification is True


def test_runtime_settings_default_to_local_backend_and_validate_browser_use(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    assert store.load()["browser_agent"] == {
        "backend": "local",
        "enabled": False,
        "allow_unrestricted_domains": False,
        "max_steps": 50,
        "max_duration_seconds": 1200,
    }

    saved = store.update(
        {
            "browser_agent": {
                "backend": "browser_use",
                "enabled": True,
                "max_steps": 25,
                "max_duration_seconds": 600,
            }
        },
        {},
    )
    assert saved["browser_agent"]["backend"] == "browser_use"

    with pytest.raises(ValueError, match="browser_agent.backend"):
        store.update({"browser_agent": {"backend": "untrusted"}}, {})


def test_session_bridge_preserves_managed_profile_and_cdp_identity(tmp_path: Path) -> None:
    managed_store = RuntimeConfigStore(tmp_path / "managed-var")
    profiles = tmp_path / "profiles"
    managed_store.update(
        {
            "browser": {
                "mode": "managed",
                "executable": "/opt/google/chrome/google-chrome",
                "headless": True,
            },
            "storage": {"profiles_dir": str(profiles)},
        },
        {},
    )
    managed = BrowserAgentSessionBridge(managed_store).prepare(
        run_id="run-1", profile_id="personal", allowed_domains=("example.test",)
    )
    assert managed.placement == Placement.DESKTOP_MANAGED
    assert managed.user_data_dir == (profiles / "personal").resolve()
    assert managed.browser_use_options()["executable_path"] == "/opt/google/chrome/google-chrome"
    assert managed.browser_use_options()["allowed_domains"] == ["example.test"]
    assert managed.downloads_path == (managed_store.runtime_dir / "downloads" / "run-1").resolve()

    cdp_store = RuntimeConfigStore(tmp_path / "cdp-var")
    cdp_store.update(
        {
            "browser": {
                "mode": "cdp",
                "cdp_endpoint": "http://127.0.0.1:9222",
            }
        },
        {},
    )
    attached = BrowserAgentSessionBridge(cdp_store).prepare(
        run_id="run-2", profile_id="personal", allowed_domains=("example.test",)
    )
    assert attached.placement == Placement.BROWSER_ATTACH
    assert attached.browser_use_options()["cdp_url"] == "http://127.0.0.1:9222"
    assert "user_data_dir" not in attached.browser_use_options()

    full_url_scope = BrowserAgentSessionBridge(cdp_store).prepare(
        run_id="run-4",
        profile_id="personal",
        allowed_domains=("https://example.test/catalog",),
    )
    assert full_url_scope.browser_use_options()["allowed_domains"] == ["example.test"]

    with pytest.raises(ValueError, match="profile_id"):
        BrowserAgentSessionBridge(managed_store).prepare(
            run_id="run-3", profile_id="../escape", allowed_domains=("example.test",)
        )


class _FakeChatOpenAI:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def test_model_bridge_builds_openai_compatible_browser_use_model(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {
            "model": {
                "provider": "openai-compatible",
                "base_url": "https://model.example.test/v1",
                "model": "vision-model",
            }
        },
        {"model_api_key": "secret-key"},
    )
    module = SimpleNamespace(ChatOpenAI=_FakeChatOpenAI)
    bridge = BrowserUseModelBridge(module_loader=lambda: module, python_version=(3, 12))

    model = bridge.create(store)

    assert model.kwargs == {
        "model": "vision-model",
        "api_key": "secret-key",
        "base_url": "https://model.example.test/v1",
    }


class _FakeHistory:
    def final_result(self):
        return "structured final answer"

    def is_successful(self):
        return True

    def is_validated(self):
        return None

    def urls(self):
        return ["https://example.test/result", "https://example.test/result"]

    def errors(self):
        return [None]


class _FakeAgent:
    def __init__(self) -> None:
        self.max_steps = None
        self.paused = False
        self.stopped = False

    async def run(self, *, max_steps: int):
        self.max_steps = max_steps
        return _FakeHistory()

    async def pause(self) -> None:
        self.paused = True

    async def resume(self) -> None:
        self.paused = False

    async def stop(self) -> None:
        self.stopped = True


class _PermissiveTestPolicy:
    def validate_request(self, request) -> None:
        return None

    def protect_tools(self, tools, request):
        return tools


class _FakeBrowserUseRuntime:
    def __init__(self) -> None:
        self.browser_options = None
        self.agent_options = None
        self.agent = _FakeAgent()

    def create_browser(self, **options):
        self.browser_options = options
        return object()

    def create_agent(self, **options):
        self.agent_options = options
        return self.agent


@pytest.mark.asyncio
async def test_browser_use_adapter_maps_claimed_completion_without_self_verifying(
    tmp_path: Path,
) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {
            "browser": {"mode": "cdp", "cdp_endpoint": "http://127.0.0.1:9222"},
        },
        {},
    )
    session = BrowserAgentSessionBridge(store).prepare(
        run_id="run-1", profile_id="personal", allowed_domains=("example.test",)
    )
    runtime = _FakeBrowserUseRuntime()
    tools = object()
    adapter = BrowserUseAdapter(
        model_factory=lambda: object(),
        runtime=runtime,
        controlled_tools=tools,
        security_policy=_PermissiveTestPolicy(),
    )

    result = await adapter.run(task_request(placement=Placement.BROWSER_ATTACH), session)

    assert result.status == AgentTaskStatus.COMPLETED
    assert result.verified is False
    assert result.output["final_result"] == "structured final answer"
    assert result.output["backend_validated"] is None
    assert result.visited_urls == ["https://example.test/result"]
    assert runtime.browser_options["cdp_url"] == "http://127.0.0.1:9222"
    assert runtime.agent_options["tools"] is tools
    assert runtime.agent.max_steps == 12

    await adapter.pause("run-1")
    assert runtime.agent.paused is True
    await adapter.resume("run-1")
    assert runtime.agent.paused is False
    await adapter.cancel("run-1")
    assert runtime.agent.stopped is True


@pytest.mark.asyncio
async def test_browser_use_adapter_refuses_uncontrolled_default_tools(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    session = BrowserAgentSessionBridge(store).prepare(
        run_id="run-1", profile_id="personal", allowed_domains=("example.test",)
    )
    adapter = BrowserUseAdapter(model_factory=lambda: object(), runtime=_FakeBrowserUseRuntime())

    with pytest.raises(BrowserAgentPolicyNotReady, match="controlled tools"):
        await adapter.run(task_request(), session)


def test_browser_use_is_a_pinned_python311_optional_dependency() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    source = pyproject.read_text(encoding="utf-8")
    assert "browser-agent = [\"browser-use==0.13.7; python_version >= '3.11'\"]" in source
