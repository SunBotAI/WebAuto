"""Build the active browser provider from persisted Web configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from webauto.application.settings import RuntimeConfigStore

from .contracts import BrowserProvider
from .playwright_provider import BrowserAttachProvider, DesktopManagedProvider


@dataclass(frozen=True, slots=True)
class ConfiguredBrowser:
    provider: BrowserProvider
    mode: str
    endpoint: str | None = None


def configured_browser(store: RuntimeConfigStore) -> ConfiguredBrowser:
    settings = store.load()
    browser = settings["browser"]
    storage = settings["storage"]
    mode = browser["mode"]
    if mode == "managed":
        launch_options = {}
        if browser.get("executable"):
            launch_options["executable_path"] = browser["executable"]
        provider = DesktopManagedProvider(
            Path(storage["profiles_dir"]),
            headless=bool(browser.get("headless")),
            launch_options=launch_options,
        )
        return ConfiguredBrowser(provider=provider, mode=mode)
    if mode == "cdp":
        return ConfiguredBrowser(
            provider=BrowserAttachProvider(), mode=mode, endpoint=browser["cdp_endpoint"]
        )
    raise RuntimeError("remote browser requires a paired LocalDeviceAgent or remote node")
