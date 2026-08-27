"""Google Chrome-first Playwright provider implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from webauto.domain import Placement

from .contracts import BrowserCapabilities, BrowserHealth, BrowserProvider, BrowserSession

PlaywrightStarter = Callable[[], Awaitable[Any]]


async def _default_starter() -> Any:
    from playwright.async_api import async_playwright

    return await async_playwright().start()


class DesktopManagedProvider(BrowserProvider):
    """Launch and own a Google Chrome persistent context."""

    def __init__(
        self,
        profiles_root: Path,
        *,
        playwright_starter: PlaywrightStarter | None = None,
        headless: bool = False,
        launch_options: dict[str, Any] | None = None,
    ) -> None:
        self._profiles_root = profiles_root
        self._starter = playwright_starter or _default_starter
        self._headless = headless
        self._launch_options = dict(launch_options or {})
        self._playwright: Any | None = None
        self._context: Any | None = None
        self._browser: Any | None = None

    @property
    def capabilities(self) -> BrowserCapabilities:
        return BrowserCapabilities(
            placement=Placement.DESKTOP_MANAGED,
            persistent_profile=True,
            can_launch=True,
            can_attach=True,
            supports_tracing=True,
            supports_downloads=True,
            supports_uploads=True,
            supports_multi_page=True,
        )

    async def _runtime(self) -> Any:
        if self._playwright is None:
            self._playwright = await self._starter()
        return self._playwright

    async def start(self, profile_id: str) -> BrowserSession:
        runtime = await self._runtime()
        profile_dir = self._profiles_root / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        options = {
            "user_data_dir": str(profile_dir),
            "channel": "chrome",
            "headless": self._headless,
            "accept_downloads": True,
            **self._launch_options,
        }
        self._context = await runtime.chromium.launch_persistent_context(**options)
        page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return BrowserSession(
            id=str(uuid4()),
            profile_id=profile_id,
            placement=Placement.DESKTOP_MANAGED,
            context=self._context,
            active_page=page,
            metadata={"profile_dir": str(profile_dir), "managed": True},
        )

    async def connect(self, endpoint: str, profile_id: str) -> BrowserSession:
        runtime = await self._runtime()
        self._browser = await runtime.chromium.connect_over_cdp(endpoint)
        if not self._browser.contexts:
            raise RuntimeError("attached browser exposes no context")
        context = self._browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        return BrowserSession(
            id=str(uuid4()),
            profile_id=profile_id,
            placement=Placement.BROWSER_ATTACH,
            browser=self._browser,
            context=context,
            active_page=page,
            metadata={"endpoint": endpoint, "managed": False},
        )

    async def health(self) -> BrowserHealth:
        active = self._context is not None or self._browser is not None
        return BrowserHealth(healthy=active, message="connected" if active else "not started")

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None


class BrowserAttachProvider(BrowserProvider):
    """Attach to a user-authorized Chrome CDP endpoint without owning its process."""

    def __init__(self, *, playwright_starter: PlaywrightStarter | None = None) -> None:
        self._starter = playwright_starter or _default_starter
        self._playwright: Any | None = None
        self._browser: Any | None = None

    @property
    def capabilities(self) -> BrowserCapabilities:
        return BrowserCapabilities(
            placement=Placement.BROWSER_ATTACH,
            persistent_profile=True,
            can_launch=False,
            can_attach=True,
            supports_tracing=False,
            supports_downloads=True,
            supports_uploads=True,
            supports_multi_page=True,
            limitations=("browser process lifecycle", "context launch options", "startup tracing"),
        )

    async def start(self, profile_id: str) -> BrowserSession:
        raise RuntimeError(
            "BrowserAttach cannot launch Chrome; call connect with an authorized endpoint"
        )

    async def connect(self, endpoint: str, profile_id: str) -> BrowserSession:
        self._playwright = await self._starter()
        self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
        if not self._browser.contexts:
            raise RuntimeError("attached browser exposes no context")
        context = self._browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        return BrowserSession(
            id=str(uuid4()),
            profile_id=profile_id,
            placement=Placement.BROWSER_ATTACH,
            browser=self._browser,
            context=context,
            active_page=page,
            metadata={"endpoint": endpoint, "managed": False},
        )

    async def health(self) -> BrowserHealth:
        connected = self._browser is not None
        if connected and hasattr(self._browser, "is_connected"):
            connected = bool(self._browser.is_connected())
        return BrowserHealth(
            healthy=connected, message="connected" if connected else "not connected"
        )

    async def close(self) -> None:
        # The attached Chrome process and browser connection are user-owned.
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
