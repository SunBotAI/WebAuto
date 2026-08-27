"""SQLite repositories for the v3.3 safety-critical tables.

Thin wrappers over :mod:`webauto.storage.sqlite.db` that enforce the
state-machine invariants for ActionAttempt and Approval (one-shot
consumption, idempotency key uniqueness, optimistic version bump) on top
of plain SQLite row-level transactions.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ActionAttemptRow:
    attempt_id: str
    session_id: str
    action_hash: str
    idempotency_key: str
    status: str
    prepared_facts: dict[str, object] = field(default_factory=dict)
    policy_decision_id: str | None = None
    policy_version: str | None = None
    optimistic_version: int = 1
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass
class ApprovalRow:
    approval_id: str
    attempt_id: str
    action_hash: str
    page_revision: str
    evidence_digest: str
    object_digest: str
    identity_digest: str
    policy_version: str
    expires_at_ms: int
    consumed: bool = False
    resolved: bool = False
    created_at_ms: int = 0
    updated_at_ms: int = 0


def _now_ms() -> int:
    return int(time.time() * 1000)


class ActionAttemptRepo:
    """One row per attempt, ``idempotency_key`` is unique per session."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self,
        *,
        session_id: str,
        action_hash: str,
        idempotency_key: str,
        status: str,
        prepared_facts: dict[str, object],
        policy_decision_id: str | None = None,
        policy_version: str | None = None,
    ) -> ActionAttemptRow:
        now = _now_ms()
        row = ActionAttemptRow(
            attempt_id="att-" + uuid.uuid4().hex,
            session_id=session_id,
            action_hash=action_hash,
            idempotency_key=idempotency_key,
            status=status,
            prepared_facts=prepared_facts,
            policy_decision_id=policy_decision_id,
            policy_version=policy_version,
            created_at_ms=now,
            updated_at_ms=now,
        )
        self._conn.execute(
            "INSERT INTO action_attempts "
            "(attempt_id, session_id, action_hash, idempotency_key, status, "
            " prepared_facts, policy_decision_id, policy_version, "
            " optimistic_version, created_at_ms, updated_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.attempt_id,
                row.session_id,
                row.action_hash,
                row.idempotency_key,
                row.status,
                json.dumps(row.prepared_facts, ensure_ascii=False, sort_keys=True),
                row.policy_decision_id,
                row.policy_version,
                row.optimistic_version,
                row.created_at_ms,
                row.updated_at_ms,
            ),
        )
        return row

    def get(self, attempt_id: str) -> ActionAttemptRow | None:
        row = self._conn.execute(
            "SELECT attempt_id, session_id, action_hash, idempotency_key, "
            "status, prepared_facts, policy_decision_id, policy_version, "
            "optimistic_version, created_at_ms, updated_at_ms "
            "FROM action_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            return None
        return ActionAttemptRow(
            attempt_id=row[0],
            session_id=row[1],
            action_hash=row[2],
            idempotency_key=row[3],
            status=row[4],
            prepared_facts=json.loads(row[5]) if row[5] else {},
            policy_decision_id=row[6],
            policy_version=row[7],
            optimistic_version=row[8],
            created_at_ms=row[9],
            updated_at_ms=row[10],
        )

    def update_status(
        self,
        attempt_id: str,
        *,
        expected_status: str,
        new_status: str,
        expected_version: int,
    ) -> bool:
        """Optimistic update. Returns False if the row no longer matches."""
        cur = self._conn.execute(
            "UPDATE action_attempts "
            "SET status = ?, optimistic_version = optimistic_version + 1, "
            "    updated_at_ms = ? "
            "WHERE attempt_id = ? AND status = ? AND optimistic_version = ?",
            (new_status, _now_ms(), attempt_id, expected_status, expected_version),
        )
        return cur.rowcount == 1


class ApprovalRepo:
    """One-shot Approval. ``consumed = 1`` is the terminal state."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self,
        *,
        attempt_id: str,
        action_hash: str,
        page_revision: str,
        evidence_digest: str,
        object_digest: str,
        identity_digest: str,
        policy_version: str,
        ttl_ms: int,
    ) -> ApprovalRow:
        now = _now_ms()
        row = ApprovalRow(
            approval_id="apr-" + uuid.uuid4().hex,
            attempt_id=attempt_id,
            action_hash=action_hash,
            page_revision=page_revision,
            evidence_digest=evidence_digest,
            object_digest=object_digest,
            identity_digest=identity_digest,
            policy_version=policy_version,
            expires_at_ms=now + ttl_ms,
            created_at_ms=now,
            updated_at_ms=now,
        )
        self._conn.execute(
            "INSERT INTO approvals "
            "(approval_id, attempt_id, action_hash, page_revision, "
            "evidence_digest, object_digest, identity_digest, policy_version, "
            "expires_at_ms, consumed, resolved, created_at_ms, updated_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
            (
                row.approval_id,
                row.attempt_id,
                row.action_hash,
                row.page_revision,
                row.evidence_digest,
                row.object_digest,
                row.identity_digest,
                row.policy_version,
                row.expires_at_ms,
                row.created_at_ms,
                row.updated_at_ms,
            ),
        )
        return row

    def get(self, approval_id: str) -> ApprovalRow | None:
        row = self._conn.execute(
            "SELECT approval_id, attempt_id, action_hash, page_revision, "
            "evidence_digest, object_digest, identity_digest, policy_version, "
            "expires_at_ms, consumed, resolved, created_at_ms, updated_at_ms "
            "FROM approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return ApprovalRow(
            approval_id=row[0],
            attempt_id=row[1],
            action_hash=row[2],
            page_revision=row[3],
            evidence_digest=row[4],
            object_digest=row[5],
            identity_digest=row[6],
            policy_version=row[7],
            expires_at_ms=row[8],
            consumed=bool(row[9]),
            resolved=bool(row[10]),
            created_at_ms=row[11],
            updated_at_ms=row[12],
        )

    def consume(self, approval_id: str, *, expected_version_digest: str) -> bool:
        """Atomically transition consumed 0 → 1, only if the binding still matches."""
        cur = self._conn.execute(
            "UPDATE approvals SET consumed = 1, updated_at_ms = ? "
            "WHERE approval_id = ? AND consumed = 0 "
            "  AND object_digest = ?",
            (_now_ms(), approval_id, expected_version_digest),
        )
        return cur.rowcount == 1

    def mark_resolved(self, approval_id: str) -> None:
        self._conn.execute(
            "UPDATE approvals SET resolved = 1, updated_at_ms = ? "
            "WHERE approval_id = ?",
            (_now_ms(), approval_id),
        )


def append_audit(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    attempt_id: str | None,
    action_type: str,
    error_code: str | None,
    evidence_ids: list[str],
    actor: str,
) -> str:
    event_id = "aud-" + uuid.uuid4().hex
    conn.execute(
        "INSERT INTO audit_events "
        "(event_id, session_id, attempt_id, action_type, error_code, "
        "evidence_ids, actor, created_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            session_id,
            attempt_id,
            action_type,
            error_code,
            json.dumps(evidence_ids, ensure_ascii=False),
            actor,
            _now_ms(),
        ),
    )
    return event_id
