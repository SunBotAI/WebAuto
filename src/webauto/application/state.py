"""Durable state port for the product-facing application service."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol


class ApplicationStateStore(Protocol):
    async def load(self) -> dict[str, Any] | None: ...

    async def save(self, state: dict[str, Any]) -> None: ...


class InMemoryApplicationStateStore:
    """Test/local store whose object can be shared across service restarts."""

    def __init__(self) -> None:
        self._state: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def load(self) -> dict[str, Any] | None:
        async with self._lock:
            return deepcopy(self._state)

    async def save(self, state: dict[str, Any]) -> None:
        async with self._lock:
            self._state = deepcopy(state)


class JsonApplicationStateStore:
    """Atomic, explicit development fallback; production should use PostgreSQL."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def load(self) -> dict[str, Any] | None:
        async with self._lock:
            if not self.path.exists():
                return None
            return json.loads(self.path.read_text(encoding="utf-8"))

    async def save(self, state: dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
