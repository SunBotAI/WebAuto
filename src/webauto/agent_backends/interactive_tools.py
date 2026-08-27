"""Low-risk interactive Browser Use tools with upstream expansion denied by default."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from webauto.domain import AgentTaskRequest

from .tools import (
    READ_ONLY_BROWSER_USE_ACTIONS,
    BrowserUseToolsContractError,
)
from .write_grants import BrowserWriteGrantAuthority

LOW_RISK_BROWSER_USE_ACTIONS = READ_ONLY_BROWSER_USE_ACTIONS | frozenset(
    {
        "click",
        "input",
        "close",
        "select_dropdown",
    }
)

_REQUIRED_INTERACTIVE_ACTIONS = frozenset(
    {"done", "search", "navigate", "extract", "click", "input"}
)


class BrowserUseInteractiveToolsFactory:
    """Expose reversible page interaction while keeping submit authority external.

    Click and input are wrapped by :class:`BrowserAgentSecurityPolicy` after this
    allowlist is applied. Uploads, arbitrary JavaScript, filesystem tools and raw
    key sequences remain disabled.
    """

    def __init__(
        self,
        module_loader: Callable[[], Any] | None = None,
        *,
        write_grants: BrowserWriteGrantAuthority | None = None,
    ) -> None:
        self._module_loader = module_loader or (lambda: import_module("browser_use"))
        self._write_grants = write_grants or BrowserWriteGrantAuthority()

    def create(self, request: AgentTaskRequest | None = None) -> Any:
        module = self._module_loader()
        tools = module.Tools(display_files_in_done_text=False)
        actions = self._actions(tools)
        missing = sorted(_REQUIRED_INTERACTIVE_ACTIONS - set(actions))
        if missing:
            raise BrowserUseToolsContractError(
                "Browser Use is missing required interactive actions: " + ", ".join(missing)
            )
        allowed = set(LOW_RISK_BROWSER_USE_ACTIONS)
        if request is not None and request.available_files:
            try:
                grant = self._write_grants.validate_request(request)
            except PermissionError as exc:
                raise BrowserUseToolsContractError(str(exc)) from exc
            if grant.operation != "xianyu_publish":
                raise BrowserUseToolsContractError(
                    "only an approved Xianyu publish may expose upload_file"
                )
            if "upload_file" not in actions:
                raise BrowserUseToolsContractError(
                    "Browser Use is missing the approved upload action"
                )
            allowed.add("upload_file")
        for name in tuple(actions):
            if name not in allowed:
                tools.exclude_action(name)
        remaining = set(self._actions(tools))
        unexpected = sorted(remaining - allowed)
        if unexpected:
            raise BrowserUseToolsContractError(
                "Browser Use exposed actions outside the WebAuto interactive allowlist: "
                + ", ".join(unexpected)
            )
        return tools

    @staticmethod
    def _actions(tools: Any) -> dict[str, Any]:
        try:
            actions = tools.registry.registry.actions
        except AttributeError as exc:
            raise BrowserUseToolsContractError(
                "Browser Use tools registry shape is incompatible with WebAuto"
            ) from exc
        if not isinstance(actions, dict):
            raise BrowserUseToolsContractError("Browser Use tools registry must be a mapping")
        return actions


__all__ = ["LOW_RISK_BROWSER_USE_ACTIONS", "BrowserUseInteractiveToolsFactory"]
