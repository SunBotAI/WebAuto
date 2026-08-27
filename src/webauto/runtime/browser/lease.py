"""Profile/session lease rules with fencing tokens."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from webauto.domain import Placement


class LeaseConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProfileLease:
    id: str
    profile_id: str
    holder_id: str
    placement: Placement
    fencing_token: int
    expires_at: datetime


class InMemoryLeaseManager:
    def __init__(self) -> None:
        self._active: dict[str, ProfileLease] = {}
        self._tokens: dict[str, int] = {}
        self._placements: dict[str, Placement] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        profile_id: str,
        holder_id: str,
        placement: Placement,
        ttl_seconds: int = 60,
    ) -> ProfileLease:
        async with self._lock:
            now = datetime.now(timezone.utc)
            current = self._active.get(profile_id)
            if current is not None and current.expires_at > now:
                raise LeaseConflict(f"profile {profile_id} already has a writer")
            bound = self._placements.get(profile_id)
            if bound is not None and bound != placement:
                raise LeaseConflict(
                    f"profile {profile_id} placement is bound to {bound.value}; explicit migration required"
                )
            token = self._tokens.get(profile_id, 0) + 1
            lease = ProfileLease(
                id=str(uuid4()),
                profile_id=profile_id,
                holder_id=holder_id,
                placement=placement,
                fencing_token=token,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            self._tokens[profile_id] = token
            self._placements[profile_id] = placement
            self._active[profile_id] = lease
            return lease

    async def release(self, lease: ProfileLease) -> None:
        async with self._lock:
            current = self._active.get(lease.profile_id)
            if current is None:
                return
            if current.id != lease.id or current.fencing_token != lease.fencing_token:
                raise LeaseConflict("stale lease cannot release the current writer")
            del self._active[lease.profile_id]

    async def validate(self, lease: ProfileLease) -> bool:
        async with self._lock:
            current = self._active.get(lease.profile_id)
            return (
                current is not None
                and current.id == lease.id
                and current.fencing_token == lease.fencing_token
                and current.expires_at > datetime.now(timezone.utc)
            )
