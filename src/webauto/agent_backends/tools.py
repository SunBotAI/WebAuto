"""Strict Browser Use tool policies owned by WebAuto."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any


class BrowserUseToolsContractError(RuntimeError):
    """Raised when an installed Browser Use tool registry is incompatible."""


READ_ONLY_BROWSER_USE_ACTIONS = frozenset(
    {
        "done",
        "search",
        "navigate",
        "go_back",
        "wait",
        "switch",
        "extract",
        "search_page",
        "find_elements",
        "scroll",
        "find_text",
        "screenshot",
        "dropdown_options",
    }
)

_REQUIRED_ACTIONS = frozenset({"done", "search", "navigate", "extract"})


class BrowserUseReadOnlyToolsFactory:
    """Create a fresh registry and remove every action outside an explicit allowlist.

    The allowlist is applied after Browser Use registers its defaults. This makes a
    newly added upstream action disabled by default instead of silently expanding
    WebAuto's authority after a dependency upgrade.
    """

    def __init__(self, module_loader: Callable[[], Any] | None = None) -> None:
        self._module_loader = module_loader or (lambda: import_module("browser_use"))

    def create(self) -> Any:
        module = self._module_loader()
        tools = module.Tools(display_files_in_done_text=False)
        actions = self._actions(tools)
        missing = sorted(_REQUIRED_ACTIONS - set(actions))
        if missing:
            raise BrowserUseToolsContractError(
                "Browser Use is missing required read-only actions: " + ", ".join(missing)
            )
        for name in tuple(actions):
            if name not in READ_ONLY_BROWSER_USE_ACTIONS:
                tools.exclude_action(name)
        remaining = set(self._actions(tools))
        unexpected = sorted(remaining - READ_ONLY_BROWSER_USE_ACTIONS)
        if unexpected:
            raise BrowserUseToolsContractError(
                "Browser Use exposed actions outside the WebAuto allowlist: "
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
