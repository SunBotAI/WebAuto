"""Bounded recovery and non-idempotent commit state machines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from webauto.domain import IdempotencyClass


class RecoveryStage(str, Enum):
    REGROUNDED = "regrounded"
    SITE_SKILL = "site_skill"
    GENERAL_AGENT = "general_agent"
    PROVIDER_SWITCH = "provider_switch"
    HUMAN_TAKEOVER = "human_takeover"


class RecoveryExhausted(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    number: int
    stage: RecoveryStage


class FallbackChain:
    _stages = tuple(RecoveryStage)

    def __init__(self, max_recoveries: int = 5) -> None:
        if max_recoveries < 0:
            raise ValueError("max_recoveries must be non-negative")
        self._limit = min(max_recoveries, len(self._stages))
        self._cursor = 0

    def next(self) -> RecoveryAttempt:
        if self._cursor >= self._limit:
            raise RecoveryExhausted("recovery budget exhausted")
        attempt = RecoveryAttempt(self._cursor + 1, self._stages[self._cursor])
        self._cursor += 1
        return attempt


class CommitState(str, Enum):
    READY = "ready"
    SUBMITTING = "submitting"
    VERIFYING_COMMIT = "verifying_commit"
    REAPPROVAL_REQUIRED = "reapproval_required"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class CommitGuard:
    def __init__(self, idempotency: IdempotencyClass, approval_id: str | None = None) -> None:
        self.idempotency = idempotency
        self.approval_id = approval_id
        self.state = CommitState.READY

    def begin_submit(self) -> None:
        if self.state == CommitState.VERIFYING_COMMIT:
            raise RuntimeError("query business result before another submit")
        if self.state == CommitState.REAPPROVAL_REQUIRED:
            raise RuntimeError("new approval is required before another submit")
        if self.state not in {CommitState.READY, CommitState.FAILED}:
            raise RuntimeError(f"cannot submit from {self.state.value}")
        self.state = CommitState.SUBMITTING

    def mark_transport_unknown(self) -> None:
        if self.state != CommitState.SUBMITTING:
            raise RuntimeError("no submit is in progress")
        self.state = CommitState.VERIFYING_COMMIT

    def record_query(self, *, found: bool) -> None:
        if self.state != CommitState.VERIFYING_COMMIT:
            raise RuntimeError("commit is not awaiting a result query")
        if found:
            self.state = CommitState.CONFIRMED
        elif self.idempotency == IdempotencyClass.NON_IDEMPOTENT:
            self.state = CommitState.REAPPROVAL_REQUIRED
        else:
            self.state = CommitState.READY

    def reapprove(self, approval_id: str) -> None:
        if self.state != CommitState.REAPPROVAL_REQUIRED:
            raise RuntimeError("commit is not awaiting reapproval")
        if not approval_id or approval_id == self.approval_id:
            raise ValueError("reapproval must have a new approval id")
        self.approval_id = approval_id
        self.state = CommitState.READY

    def confirm(self) -> None:
        if self.state != CommitState.SUBMITTING:
            raise RuntimeError("no submit is in progress")
        self.state = CommitState.CONFIRMED
