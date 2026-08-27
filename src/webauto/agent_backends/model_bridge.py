"""Build Browser Use LLM objects from WebAuto's encrypted model configuration."""

from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import import_module
from typing import Any

from webauto.application.settings import RuntimeConfigStore


class BrowserUseDependencyError(RuntimeError):
    pass


class BrowserUseModelBridge:
    def __init__(
        self,
        *,
        module_loader: Callable[[], Any] | None = None,
        python_version: tuple[int, int] | None = None,
    ) -> None:
        self._module_loader = module_loader or (lambda: import_module("browser_use"))
        self._python_version = python_version or sys.version_info[:2]

    def create(self, store: RuntimeConfigStore) -> Any:
        if self._python_version < (3, 11):
            raise BrowserUseDependencyError("Browser Use requires Python 3.11 or newer")
        settings = store.load()["model"]
        provider = str(settings.get("provider") or "").strip().lower()
        model_name = str(settings.get("model") or "").strip()
        api_key = store.secret("model_api_key")
        if not model_name:
            raise ValueError("a model name is required for the Browser Use backend")
        if not api_key:
            raise ValueError("a model API key is required for the Browser Use backend")
        try:
            module = self._module_loader()
        except ImportError as exc:
            raise BrowserUseDependencyError(
                "Browser Use is not installed; install the 'browser-agent' extra"
            ) from exc

        if provider in {"openai", "openai-compatible"}:
            options = {"model": model_name, "api_key": api_key}
            base_url = str(settings.get("base_url") or "").strip()
            if base_url:
                options["base_url"] = base_url
            return module.ChatOpenAI(**options)
        if provider in {"browser-use", "browser_use"}:
            return module.ChatBrowserUse(model=model_name, api_key=api_key)
        raise ValueError(f"unsupported Browser Use model provider: {provider or '<blank>'}")
