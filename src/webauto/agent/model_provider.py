"""Text/vision model provider boundary with bounded fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ModelRequest:
    task: str
    payload: dict[str, Any]
    timeout_seconds: float = 30


@dataclass(frozen=True, slots=True)
class ModelResponse:
    provider: str
    content: dict[str, Any]
    cost: float = 0
    latency_ms: float | None = None


class ModelProvider(Protocol):
    name: str

    async def complete(self, request: ModelRequest) -> ModelResponse: ...


class FallbackModelProvider:
    def __init__(self, providers: list[ModelProvider]) -> None:
        if not providers:
            raise ValueError("at least one model provider is required")
        self._providers = tuple(providers)
        self._attempts: list[tuple[str, str]] = []

    @property
    def attempts(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._attempts)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self._attempts.clear()
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                response = await provider.complete(request)
                self._attempts.append((provider.name, "success"))
                return response
            except TimeoutError as exc:
                last_error = exc
                self._attempts.append((provider.name, "timeout"))
            except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                last_error = exc
                self._attempts.append((provider.name, "error"))
        raise RuntimeError("all model providers failed") from last_error
