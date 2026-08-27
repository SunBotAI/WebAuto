"""Playwright provider contract tests using an injected runtime double."""

from pathlib import Path

import pytest

from webauto.domain import Placement
from webauto.runtime.browser.playwright_provider import (
    BrowserAttachProvider,
    DesktopManagedProvider,
)


class FakePage:
    url = "about:blank"


class FakeContext:
    def __init__(self) -> None:
        self.pages = [FakePage()]
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.contexts = [context]
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self) -> None:
        self.context = FakeContext()
        self.browser = FakeBrowser(self.context)
        self.launch_kwargs = None
        self.endpoint = None

    async def launch_persistent_context(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.context

    async def connect_over_cdp(self, endpoint: str):
        self.endpoint = endpoint
        return self.browser


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_desktop_managed_launches_google_chrome_with_profile(tmp_path: Path) -> None:
    runtime = FakePlaywright()

    async def starter():
        return runtime

    provider = DesktopManagedProvider(tmp_path, playwright_starter=starter, headless=True)
    session = await provider.start("profile-1")

    assert session.placement == Placement.DESKTOP_MANAGED
    assert runtime.chromium.launch_kwargs["channel"] == "chrome"
    assert runtime.chromium.launch_kwargs["user_data_dir"] == str(tmp_path / "profile-1")
    assert provider.capabilities.persistent_profile

    await provider.close()
    assert runtime.chromium.context.closed
    assert runtime.stopped


@pytest.mark.asyncio
async def test_browser_attach_connects_without_claiming_launch_control() -> None:
    runtime = FakePlaywright()

    async def starter():
        return runtime

    provider = BrowserAttachProvider(playwright_starter=starter)
    session = await provider.connect("http://127.0.0.1:9222", "profile-existing")

    assert session.placement == Placement.BROWSER_ATTACH
    assert runtime.chromium.endpoint == "http://127.0.0.1:9222"
    assert not provider.capabilities.can_launch
    assert "browser process lifecycle" in provider.capabilities.limitations

    await provider.close()
    assert not runtime.chromium.browser.closed
    assert runtime.stopped


@pytest.mark.asyncio
async def test_attach_provider_refuses_start() -> None:
    provider = BrowserAttachProvider()
    with pytest.raises(RuntimeError, match="connect"):
        await provider.start("profile-1")
