"""Capture a provider-neutral multimodal PageState."""

from __future__ import annotations

from typing import Any

from webauto.domain import PageState
from webauto.runtime.artifacts import LocalArtifactStore

from .contracts import BrowserSession

_FORM_SCRIPT = """
elements => Object.fromEntries(elements.map((el, index) => [
  el.name ? `${el.tagName.toLowerCase()}[name=${el.name}]` : `${el.tagName.toLowerCase()}#${el.id || index}`,
  el.type === 'password' ? '<redacted>' : (el.value ?? '')
]))
"""


class BrowserObserver:
    def __init__(self, artifacts: LocalArtifactStore) -> None:
        self._artifacts = artifacts

    async def observe(self, session: BrowserSession) -> PageState:
        page = session.active_page
        if page is None:
            raise RuntimeError("browser session has no active page")

        title = await page.title()
        dom = await page.content()
        accessibility: dict[str, Any] | None = None
        try:
            snapshot = await page.locator("body").aria_snapshot()
            accessibility = {"snapshot": snapshot}
        except (AttributeError, NotImplementedError):
            accessibility = None

        form_values: dict[str, Any] = {}
        try:
            form_values = await page.locator("input, textarea, select").evaluate_all(_FORM_SCRIPT)
        except (AttributeError, NotImplementedError):
            pass

        screenshot = await page.screenshot(type="png", full_page=False)
        screenshot_id = await self._artifacts.put(screenshot, extension="png")
        return PageState(
            url=page.url,
            title=title,
            dom_snapshot=dom,
            accessibility_snapshot=accessibility,
            screenshot_artifact_id=screenshot_id,
            network_events=list(session.metadata.get("network_events", [])),
            form_values=form_values,
            focused_element=session.metadata.get("focused_element"),
            dialogs=list(session.metadata.get("dialogs", [])),
            browser_state={
                "session_id": session.id,
                "profile_id": session.profile_id,
                "placement": session.placement.value,
            },
        )
