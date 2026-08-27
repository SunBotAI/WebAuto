"""Provider-neutral browser runtime contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from webauto.domain import Placement


@dataclass(frozen=True, slots=True)
class BrowserCapabilities:
    placement: Placement
    persistent_profile: bool
    can_launch: bool
    can_attach: bool
    supports_tracing: bool
    supports_downloads: bool
    supports_uploads: bool
    supports_multi_page: bool
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BrowserHealth:
    healthy: bool
    message: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class BrowserSession:
    id: str
    profile_id: str
    placement: Placement
    browser: Any | None = None
    context: Any | None = None
    active_page: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BrowserProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> BrowserCapabilities: ...

    @abstractmethod
    async def start(self, profile_id: str) -> BrowserSession: ...

    @abstractmethod
    async def connect(self, endpoint: str, profile_id: str) -> BrowserSession: ...

    @abstractmethod
    async def health(self) -> BrowserHealth: ...

    @abstractmethod
    async def close(self) -> None: ...


class ControlOwner(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


class BrowserControl:
    """Mutual exclusion between autonomous execution and human takeover."""

    def __init__(self) -> None:
        self._owner: ControlOwner | None = None

    @property
    def owner(self) -> ControlOwner | None:
        return self._owner

    async def acquire(self, owner: ControlOwner) -> None:
        if self._owner is not None and self._owner != owner:
            raise RuntimeError(f"browser is controlled by {self._owner.value}")
        if self._owner == owner:
            raise RuntimeError(f"browser is already controlled by {owner.value}")
        self._owner = owner

    async def release(self, owner: ControlOwner) -> None:
        if self._owner != owner:
            raise RuntimeError(f"browser is not controlled by {owner.value}")
        self._owner = None
