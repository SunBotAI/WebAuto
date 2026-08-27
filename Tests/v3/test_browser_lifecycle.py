"""Multi-page lifecycle and live-control tests."""

import pytest

from webauto.domain import Placement
from webauto.runtime.browser import BrowserControl, BrowserSession, ControlOwner
from webauto.runtime.browser.lifecycle import PageLifecycle
from webauto.runtime.browser.live import LiveBrowserController, LiveState


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.frames = [f"frame:{url}"]
        self.closed = False

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


def make_session():
    pages = [FakePage("https://one.test"), FakePage("https://two.test")]
    return BrowserSession(
        id="session-1",
        profile_id="profile-1",
        placement=Placement.DESKTOP_MANAGED,
        context=FakeContext(pages),
        active_page=pages[0],
    )


@pytest.mark.asyncio
async def test_page_lifecycle_switches_and_closes_tabs() -> None:
    session = make_session()
    lifecycle = PageLifecycle(session)

    assert lifecycle.pages == tuple(session.context.pages)
    lifecycle.activate(1)
    assert session.active_page.url == "https://two.test"
    assert lifecycle.frames == ("frame:https://two.test",)

    await lifecycle.close_active()
    assert session.active_page.url == "https://one.test"


@pytest.mark.asyncio
async def test_live_controller_pause_takeover_and_return() -> None:
    control = BrowserControl()
    live = LiveBrowserController(control)
    await live.start_agent_control()
    assert live.state == LiveState.AGENT

    await live.pause()
    assert live.state == LiveState.PAUSED

    await live.takeover()
    assert control.owner == ControlOwner.HUMAN
    assert live.state == LiveState.HUMAN

    await live.return_to_agent()
    assert control.owner == ControlOwner.AGENT
    assert live.state == LiveState.AGENT
