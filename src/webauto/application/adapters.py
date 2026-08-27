"""Transport-neutral product adapters backed by :class:`ApplicationService`."""

from __future__ import annotations

import inspect
from typing import Any

from .service import ApplicationService


class _ServiceAdapter:
    def __init__(self, service: ApplicationService) -> None:
        self.service = service

    async def invoke(self, operation: str, /, **arguments: Any) -> Any:
        """Invoke a public application operation without exposing internals."""
        if not operation or operation.startswith("_"):
            raise ValueError("a public application operation is required")
        target = getattr(self.service, operation, None)
        if target is None or not callable(target):
            raise ValueError(f"unknown application operation: {operation}")
        result = target(**arguments)
        return await result if inspect.isawaitable(result) else result


class CliAdapter(_ServiceAdapter):
    """Boundary used by command-line handlers."""


class McpAdapter(_ServiceAdapter):
    """Boundary used by MCP tool handlers."""


class WebAdapter(_ServiceAdapter):
    """Boundary used by HTTP and dashboard handlers."""
