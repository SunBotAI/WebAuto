"""Observer, grounding and action execution tests with a browser double."""

from pathlib import Path

import pytest

from webauto.domain import (
    Action,
    ActionKind,
    IdempotencyClass,
    Placement,
    RiskLevel,
    VerificationResult,
    VerificationStatus,
    VerifierSpec,
)
from webauto.runtime.artifacts import LocalArtifactStore
from webauto.runtime.browser import BrowserControl, BrowserSession, ControlOwner
from webauto.runtime.browser.executor import ActionExecutor
from webauto.runtime.browser.grounder import GroundingTarget, PageStateGrounder
from webauto.runtime.browser.observer import BrowserObserver


class FakeLocator:
    def __init__(self, page, selector: str) -> None:
        self.page = page
        self.selector = selector

    async def aria_snapshot(self):
        return '- main:\n  - button "提交"'

    async def evaluate_all(self, script):
        return {"input[name=title]": "测试商品"}

    async def click(self):
        self.page.calls.append(("click", self.selector))

    async def fill(self, value):
        self.page.calls.append(("fill", self.selector, value))

    async def select_option(self, value):
        self.page.calls.append(("select", self.selector, value))

    async def set_input_files(self, files):
        self.page.calls.append(("upload", self.selector, files))

    async def text_content(self):
        return "结果文本"


class FakePage:
    url = "https://example.test/form"

    def __init__(self) -> None:
        self.calls = []

    async def title(self):
        return "测试表单"

    async def content(self):
        return '<main><button id="submit">提交</button></main>'

    async def screenshot(self, **kwargs):
        return b"fake-png"

    def locator(self, selector):
        return FakeLocator(self, selector)

    def get_by_role(self, role, name=None):
        return FakeLocator(self, f"role={role},name={name}")

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", url))
        self.url = url

    async def wait_for_timeout(self, milliseconds):
        self.calls.append(("wait", milliseconds))


def make_session(page: FakePage, placement=Placement.DESKTOP_MANAGED):
    return BrowserSession(
        id="session-1",
        profile_id="profile-1",
        placement=placement,
        active_page=page,
        metadata={
            "network_events": [{"method": "GET", "status": 200}],
            "dialogs": [],
        },
    )


@pytest.mark.asyncio
async def test_observer_captures_multimodal_page_state(tmp_path: Path) -> None:
    page = FakePage()
    observer = BrowserObserver(LocalArtifactStore(tmp_path))

    state = await observer.observe(make_session(page))

    assert state.url == "https://example.test/form"
    assert "button" in state.dom_snapshot
    assert "提交" in state.accessibility_snapshot["snapshot"]
    assert state.form_values["input[name=title]"] == "测试商品"
    assert state.screenshot_artifact_id
    assert (tmp_path / f"{state.screenshot_artifact_id}.png").exists()


def test_grounder_combines_landmark_accessibility_and_dom() -> None:
    from webauto.domain import PageState

    state = PageState(
        url="https://example.test",
        dom_snapshot='<button id="submit">提交</button>',
        accessibility_snapshot={"snapshot": '- button "提交"'},
    )
    grounder = PageStateGrounder(landmarks={"submit": "#submit"})

    candidates = grounder.ground(
        GroundingTarget(name="提交", role="button", landmark="submit"), state
    )

    assert candidates[0].selector == "#submit"
    assert candidates[0].confidence > candidates[-1].confidence


@pytest.mark.asyncio
@pytest.mark.parametrize("placement", [Placement.DESKTOP_MANAGED, Placement.BROWSER_ATTACH])
async def test_same_action_executes_for_both_provider_sessions(
    placement: Placement, tmp_path: Path
) -> None:
    page = FakePage()
    observer = BrowserObserver(LocalArtifactStore(tmp_path))
    control = BrowserControl()
    await control.acquire(ControlOwner.AGENT)

    async def verify(action, state):
        return VerificationResult(status=VerificationStatus.PASSED, summary="页面已回读")

    executor = ActionExecutor(observer=observer, verifier=verify, control=control)
    action = Action(
        kind=ActionKind.CLICK,
        target={"role": "button", "name": "提交"},
        preconditions=["button_visible"],
        risk_level=RiskLevel.L1,
        idempotency=IdempotencyClass.IDEMPOTENT,
        verifier=VerifierSpec(kind="page_state", expectation={"changed": True}),
    )

    result = await executor.execute(action, make_session(page, placement))

    assert result.succeeded
    assert page.calls == [("click", "role=button,name=提交")]


@pytest.mark.asyncio
async def test_agent_execution_is_blocked_during_human_takeover(tmp_path: Path) -> None:
    page = FakePage()
    control = BrowserControl()
    await control.acquire(ControlOwner.HUMAN)

    async def verify(action, state):
        return VerificationResult(status=VerificationStatus.PASSED, summary="ok")

    executor = ActionExecutor(
        observer=BrowserObserver(LocalArtifactStore(tmp_path)), verifier=verify, control=control
    )
    action = Action(
        kind=ActionKind.CLICK,
        target={"selector": "#submit"},
        preconditions=["visible"],
        risk_level=RiskLevel.L1,
        idempotency=IdempotencyClass.IDEMPOTENT,
        verifier=VerifierSpec(kind="page_state", expectation={"changed": True}),
    )

    with pytest.raises(RuntimeError, match="human"):
        await executor.execute(action, make_session(page))


class ChallengePage(FakePage):
    async def content(self):
        return "<html><body><h1>请完成滑块验证码</h1><p>安全验证后继续</p></body></html>"


@pytest.mark.asyncio
async def test_action_stops_after_challenge_and_does_not_claim_success(tmp_path: Path) -> None:
    page = ChallengePage()
    control = BrowserControl()
    await control.acquire(ControlOwner.AGENT)
    verifier_called = False

    async def verify(action, state):
        nonlocal verifier_called
        verifier_called = True
        return VerificationResult(status=VerificationStatus.PASSED, summary="should not run")

    executor = ActionExecutor(
        observer=BrowserObserver(LocalArtifactStore(tmp_path)), verifier=verify, control=control
    )
    action = Action(
        kind=ActionKind.WAIT,
        arguments={"seconds": 0},
        target={"selector": "body"},
        preconditions=["page_visible"],
        risk_level=RiskLevel.L0,
        idempotency=IdempotencyClass.READ_ONLY,
        verifier=VerifierSpec(kind="page_state", expectation={"dom_nonempty": True}),
    )
    result = await executor.execute(action, make_session(page))
    assert result.status.value == "blocked"
    assert result.output["challenge"] == "captcha"
    assert result.output["requires_human"] is True
    assert verifier_called is False
