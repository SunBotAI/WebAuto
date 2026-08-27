"""Repository protocols used by application services."""

from __future__ import annotations

from typing import Protocol, TypeVar

EntityT = TypeVar("EntityT")


class Repository(Protocol[EntityT]):
    async def get(self, entity_id: str) -> EntityT | None: ...

    async def add(self, entity: EntityT) -> None: ...

    async def save(self, entity: EntityT) -> None: ...


class OutboxRepository(Protocol):
    async def add(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> str: ...
