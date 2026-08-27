"""Capability registry with immutable version keys."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import CapabilityDefinition


class CapabilityRegistry:
    def __init__(self, capabilities: Iterable[CapabilityDefinition] = ()) -> None:
        self._items: dict[tuple[str, str], CapabilityDefinition] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: CapabilityDefinition) -> None:
        if capability.key in self._items:
            name, version = capability.key
            raise ValueError(f"capability {name}@{version} is already registered")
        self._items[capability.key] = capability

    def get(self, name: str, version: str) -> CapabilityDefinition:
        try:
            return self._items[(name, version)]
        except KeyError as exc:
            raise KeyError(f"unknown capability {name}@{version}") from exc

    def list(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(self._items[key] for key in sorted(self._items))
