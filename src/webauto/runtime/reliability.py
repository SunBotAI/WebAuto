"""Reliable-run primitives shared by workers and persistence adapters."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from webauto.domain import Action, Approval, ApprovalState, PageState, Placement


def action_digest(action: Action) -> str:
    payload = action.model_dump(mode="json", exclude={"approval_id"})
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_binding_digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalService:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._items: dict[str, Approval] = {}

    def request(
        self,
        *,
        run_id: str,
        step_id: str | None,
        action: Action,
        profile_id: str,
        placement: Placement,
        preview: dict[str, Any],
        diff: dict[str, Any],
        page_revision: str,
        evidence_ids: list[str],
        object_scope: dict[str, Any],
        ttl: timedelta,
    ) -> Approval:
        if ttl.total_seconds() <= 0:
            raise ValueError("approval ttl must be positive")
        if not page_revision.strip():
            raise ValueError("approval page_revision is required")
        if not evidence_ids or not all(item.strip() for item in evidence_ids):
            raise ValueError("approval requires non-blank evidence_ids")
        if not object_scope:
            raise ValueError("approval object_scope is required")
        approval = Approval(
            run_id=run_id,
            step_id=step_id,
            action_hash=action_digest(action),
            profile_id=profile_id,
            placement=placement,
            risk_level=action.risk_level,
            preview=preview,
            diff=diff,
            page_revision=page_revision,
            evidence_digest=approval_binding_digest(sorted(set(evidence_ids))),
            object_digest=approval_binding_digest(object_scope),
            expires_at=self._clock() + ttl,
        )
        self._items[approval.id] = approval
        return approval

    def get(self, approval_id: str) -> Approval:
        return self._items[approval_id]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return JSON-safe approval state for durable application snapshots."""
        return {
            approval_id: approval.model_dump(mode="json")
            for approval_id, approval in self._items.items()
        }

    def restore(self, values: dict[str, dict[str, Any]]) -> None:
        """Restore approvals after a trusted state-store load."""
        self._items = {
            approval_id: Approval.model_validate(value) for approval_id, value in values.items()
        }

    def approve(self, approval_id: str, resolved_by: str) -> Approval:
        return self._resolve(approval_id, ApprovalState.APPROVED, resolved_by)

    def reject(self, approval_id: str, resolved_by: str) -> Approval:
        return self._resolve(approval_id, ApprovalState.REJECTED, resolved_by)

    def revoke(self, approval_id: str, resolved_by: str) -> Approval:
        current = self._items[approval_id]
        if current.state not in {ApprovalState.PENDING, ApprovalState.APPROVED}:
            raise RuntimeError(f"cannot revoke approval in {current.state.value}")
        return self._resolve(approval_id, ApprovalState.REVOKED, resolved_by, allow_approved=True)

    def _resolve(
        self,
        approval_id: str,
        state: ApprovalState,
        resolved_by: str,
        *,
        allow_approved: bool = False,
    ) -> Approval:
        current = self._items[approval_id]
        allowed = {ApprovalState.PENDING}
        if allow_approved:
            allowed.add(ApprovalState.APPROVED)
        if current.state not in allowed:
            raise RuntimeError(f"approval is already {current.state.value}")
        resolved = current.model_copy(
            update={"state": state, "resolved_at": self._clock(), "resolved_by": resolved_by}
        )
        self._items[approval_id] = resolved
        return resolved

    def validate(
        self,
        approval_id: str,
        action: Action,
        *,
        profile_id: str,
        placement: Placement,
        page_revision: str,
        evidence_ids: list[str],
        object_scope: dict[str, Any],
    ) -> bool:
        approval = self._items.get(approval_id)
        return bool(
            approval
            and approval.is_valid_for(
                action_hash=action_digest(action),
                profile_id=profile_id,
                placement=placement,
                page_revision=page_revision,
                evidence_digest=approval_binding_digest(sorted(set(evidence_ids))),
                object_digest=approval_binding_digest(object_scope),
                now=self._clock(),
            )
        )

    def consume(
        self,
        approval_id: str,
        action: Action,
        *,
        profile_id: str,
        placement: Placement,
        page_revision: str,
        evidence_ids: list[str],
        object_scope: dict[str, Any],
    ) -> Approval:
        if not self.validate(
            approval_id,
            action,
            profile_id=profile_id,
            placement=placement,
            page_revision=page_revision,
            evidence_ids=evidence_ids,
            object_scope=object_scope,
        ):
            raise RuntimeError("approval binding is invalid, expired, changed or already consumed")
        current = self._items[approval_id]
        consumed = current.model_copy(
            update={"state": ApprovalState.CONSUMED, "resolved_at": self._clock()}
        )
        self._items[approval_id] = consumed
        return consumed


@dataclass(frozen=True, slots=True)
class Checkpoint:
    run_id: str
    plan_id: str
    plan_version: str
    resume_node_id: str
    verified_facts: dict[str, Any]
    page_state: PageState
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._items: dict[str, list[Checkpoint]] = {}
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: Checkpoint) -> None:
        async with self._lock:
            self._items.setdefault(checkpoint.run_id, []).append(checkpoint)

    async def latest(self, run_id: str) -> Checkpoint | None:
        async with self._lock:
            items = self._items.get(run_id, [])
            return items[-1] if items else None


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    id: str
    dedupe_key: str
    due_at: datetime
    payload: dict[str, Any]


class InMemoryScheduler:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._jobs: dict[str, ScheduledJob] = {}
        self._dispatched: set[str] = set()

    def schedule(self, dedupe_key: str, due_at: datetime, payload: dict[str, Any]) -> ScheduledJob:
        if dedupe_key in self._jobs:
            return self._jobs[dedupe_key]
        job = ScheduledJob(str(uuid4()), dedupe_key, due_at, payload)
        self._jobs[dedupe_key] = job
        return job

    def due(self, *, misfire_grace: timedelta) -> tuple[ScheduledJob, ...]:
        now = self._clock()
        result: list[ScheduledJob] = []
        for job in sorted(self._jobs.values(), key=lambda item: item.due_at):
            if job.id in self._dispatched or job.due_at > now:
                continue
            self._dispatched.add(job.id)
            if now - job.due_at <= misfire_grace:
                result.append(job)
        return tuple(result)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def claim(self, key: str) -> bool:
        async with self._lock:
            if key in self._claimed:
                return False
            self._claimed.add(key)
            return True

    async def complete(self, key: str, result: dict[str, Any]) -> None:
        async with self._lock:
            if key not in self._claimed:
                raise KeyError("idempotency key was not claimed")
            self._results[key] = result

    async def result(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._results.get(key)

    async def abandon(self, key: str) -> None:
        async with self._lock:
            if key not in self._results:
                self._claimed.discard(key)


class WorkerHeartbeatRegistry:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._heartbeats: dict[str, datetime] = {}

    def beat(self, worker_id: str, *, observed_at: datetime | None = None) -> None:
        self._heartbeats[worker_id] = observed_at or self._clock()

    def stale(self, max_age: timedelta) -> tuple[str, ...]:
        threshold = self._clock() - max_age
        return tuple(
            sorted(worker for worker, seen in self._heartbeats.items() if seen < threshold)
        )
