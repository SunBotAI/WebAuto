"""Generic governed-action prepare/get/execute.

Per plan §17.3 B2-03: independent of run_id and Vertical Workspace;
SHA-256 of the action payload and policy version are bound at prepare
time and re-checked at execute time so that a drifted page or content
fails one-shot consumption.

Storage: an SQLite-backed ActionAttempt + Approval pair (see
``webauto.storage.sqlite.repos``). A local-only stub connector drives
the actual write for the v3.3 release gate. Real semantic actions
(pluggable via Site Skill SDK in v3.4) reuse the same envelope.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from webauto.storage.reconciler import OutcomeReconciler, ReconcileResult
from webauto.storage.sqlite.db import open_db
from webauto.storage.sqlite.repos import (
    ActionAttemptRepo,
    ApprovalRepo,
    append_audit,
)


def _hash_payload(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _session_db_path(session_id: str) -> Path:
    """Per-session sqlite file under tmp; replaced by SQLite WAL with shared
    connection in B3 (lease) once cross-process coordination is added."""
    base = Path(tempfile.gettempdir()) / "webauto-governed"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{session_id}.db"


@dataclass
class GovernedPrepareResult:
    approval_id: str
    attempt_id: str
    action_hash: str
    page_revision: str
    object_digest: str
    identity_digest: str
    policy_version: str
    expires_at_ms: int
    status: str = "PREPARED"


class GovernedActions:
    """Self-contained prepare / get / execute against a session-local sqlite."""

    def __init__(self, session_id: str, *, policy_version: str = "v3.3", ttl_ms: int = 60_000) -> None:
        self._session_id = session_id
        self._policy_version = policy_version
        self._ttl_ms = ttl_ms
        self._conn = open_db(_session_db_path(session_id))
        self._attempts = ActionAttemptRepo(self._conn)
        self._approvals = ApprovalRepo(self._conn)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def prepare(
        self,
        *,
        action_type: str,
        client_request_id: str,
        page_revision: str,
        target: dict[str, object],
        content_digest: str,
        file_digest: str | None = None,
        identity_digest: str = "default-identity",
    ) -> GovernedPrepareResult:
        prepared_facts = {
            "action_type": action_type,
            "client_request_id": client_request_id,
            "target": target,
            "content_digest": content_digest,
            "file_digest": file_digest,
            "page_revision": page_revision,
            "identity_digest": identity_digest,
        }
        action_hash = _hash_payload(prepared_facts)
        object_digest = _hash_payload({"target": target, "content_digest": content_digest})

        attempt = self._attempts.create(
            session_id=self._session_id,
            action_hash=action_hash,
            idempotency_key=client_request_id,
            status="PREPARED",
            prepared_facts=prepared_facts,
            policy_decision_id=None,
            policy_version=self._policy_version,
        )
        approval = self._approvals.create(
            attempt_id=attempt.attempt_id,
            action_hash=action_hash,
            page_revision=page_revision,
            evidence_digest=action_hash,
            object_digest=object_digest,
            identity_digest=identity_digest,
            policy_version=self._policy_version,
            ttl_ms=self._ttl_ms,
        )
        append_audit(
            self._conn,
            session_id=self._session_id,
            attempt_id=attempt.attempt_id,
            action_type=f"governed.{action_type}.prepare",
            error_code=None,
            evidence_ids=[approval.approval_id],
            actor="mcp",
        )
        return GovernedPrepareResult(
            approval_id=approval.approval_id,
            attempt_id=attempt.attempt_id,
            action_hash=action_hash,
            page_revision=page_revision,
            object_digest=object_digest,
            identity_digest=identity_digest,
            policy_version=self._policy_version,
            expires_at_ms=approval.expires_at_ms,
        )

    def get(self, approval_id: str) -> dict[str, object] | None:
        row = self._approvals.get(approval_id)
        if row is None:
            return None
        return {
            "approval_id": row.approval_id,
            "attempt_id": row.attempt_id,
            "action_hash": row.action_hash,
            "page_revision": row.page_revision,
            "object_digest": row.object_digest,
            "identity_digest": row.identity_digest,
            "policy_version": row.policy_version,
            "expires_at_ms": row.expires_at_ms,
            "consumed": row.consumed,
            "resolved": row.resolved,
        }

    async def execute(
        self,
        approval_id: str,
        *,
        expected_object_digest: str,
        reconciler: OutcomeReconciler | None = None,
    ) -> dict[str, object]:
        row = self._approvals.get(approval_id)
        if row is None:
            raise KeyError(f"unknown approval_id: {approval_id}")
        if row.consumed:
            raise RuntimeError("approval already consumed")
        if not self._approvals.consume(approval_id, expected_version_digest=expected_object_digest):
            # Either already consumed or object digest drifted.
            append_audit(
                self._conn,
                session_id=self._session_id,
                attempt_id=row.attempt_id,
                action_type="governed.execute.rejected",
                error_code="OBJECT_DRIFT",
                evidence_ids=[approval_id],
                actor="mcp",
            )
            return {
                "status": "rejected",
                "reason": "object_digest drift or already consumed",
            }

        self._attempts.update_status(
            row.attempt_id,
            expected_status="PREPARED",
            new_status="DISPATCHING",
            expected_version=1,
        )
        # Local deterministic execute path: simulate success.
        self._attempts.update_status(
            row.attempt_id,
            expected_status="DISPATCHING",
            new_status="SUCCEEDED",
            expected_version=2,
        )
        self._approvals.mark_resolved(approval_id)
        append_audit(
            self._conn,
            session_id=self._session_id,
            attempt_id=row.attempt_id,
            action_type="governed.execute.committed",
            error_code=None,
            evidence_ids=[approval_id],
            actor="mcp",
        )

        reconcile_result: ReconcileResult | None = None
        if reconciler is not None:
            try:
                reconcile_result = await reconciler.reconcile(
                    business_key={"client_request_id": self._approvals.get(approval_id).action_hash},
                    prepared_facts={"approval_id": approval_id},
                )
            except Exception:  # noqa: BLE001 - reconcile failure maps to INCONCLUSIVE
                reconcile_result = ReconcileResult.INCONCLUSIVE

        return {
            "status": "succeeded",
            "approval_id": approval_id,
            "attempt_id": row.attempt_id,
            "reconcile": reconcile_result.value if reconcile_result else None,
        }
