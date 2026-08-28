"""B2-02: ActionAttempt + Approval persistence and one-shot consumption."""

from __future__ import annotations

import tempfile

import pytest

from webauto.storage.sqlite.db import open_db
from webauto.storage.sqlite.repos import (
    ActionAttemptRepo,
    ApprovalRepo,
    append_audit,
)


@pytest.fixture
def conn():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = open_db(f.name)
    yield db
    db.close()


def test_action_attempt_create_and_update(conn) -> None:
    repo = ActionAttemptRepo(conn)
    row = repo.create(
        session_id="sess-1",
        action_hash="ah-1",
        idempotency_key="idem-1",
        status="PREPARED",
        prepared_facts={"url": "https://x", "fields": ["price"]},
        policy_decision_id="dec-1",
        policy_version="v3.3",
    )
    assert row.status == "PREPARED"
    assert row.optimistic_version == 1

    ok = repo.update_status(
        row.attempt_id,
        expected_status="PREPARED",
        new_status="DISPATCHING",
        expected_version=1,
    )
    assert ok

    fetched = repo.get(row.attempt_id)
    assert fetched is not None
    assert fetched.status == "DISPATCHING"
    assert fetched.optimistic_version == 2


def test_action_attempt_optimistic_lock_blocks_stale_write(conn) -> None:
    repo = ActionAttemptRepo(conn)
    row = repo.create(
        session_id="sess-1",
        action_hash="ah-1",
        idempotency_key="idem-1",
        status="PREPARED",
        prepared_facts={},
    )
    # First caller bumps to DISPATCHING v=2
    assert repo.update_status(
        row.attempt_id, expected_status="PREPARED",
        new_status="DISPATCHING", expected_version=1,
    )
    # Second caller still sees v=1 → must fail
    assert not repo.update_status(
        row.attempt_id, expected_status="DISPATCHING",
        new_status="SUCCEEDED", expected_version=1,
    )


def test_approval_one_shot_consume(conn) -> None:
    attempts = ActionAttemptRepo(conn)
    approvals = ApprovalRepo(conn)
    att = attempts.create(
        session_id="sess-1",
        action_hash="ah-1",
        idempotency_key="idem-1",
        status="PREPARED",
        prepared_facts={},
        policy_decision_id="dec-1",
        policy_version="v3.3",
    )
    apr = approvals.create(
        attempt_id=att.attempt_id,
        action_hash=att.action_hash,
        page_revision="rev-1",
        evidence_digest="ev-1",
        object_digest="ob-1",
        identity_digest="id-1",
        policy_version="v3.3",
        ttl_ms=60_000,
    )
    # First consume succeeds
    assert approvals.approve(apr.approval_id)
    assert approvals.consume(apr.approval_id, expected_version_digest="ob-1")
    # Second consume: row already consumed (consumed=0 predicate fails)
    assert not approvals.consume(apr.approval_id, expected_version_digest="ob-1")
    fetched = approvals.get(apr.approval_id)
    assert fetched is not None
    assert fetched.consumed is True


def test_approval_consume_rejects_drifted_object(conn) -> None:
    attempts = ActionAttemptRepo(conn)
    approvals = ApprovalRepo(conn)
    att = attempts.create(
        session_id="sess-1", action_hash="ah-1", idempotency_key="idem-1",
        status="PREPARED", prepared_facts={},
    )
    apr = approvals.create(
        attempt_id=att.attempt_id, action_hash=att.action_hash,
        page_revision="rev-1", evidence_digest="ev-1",
        object_digest="ob-1", identity_digest="id-1",
        policy_version="v3.3", ttl_ms=60_000,
    )
    # Page changed between prepare and execute: object_digest no longer matches
    assert not approvals.consume(apr.approval_id, expected_version_digest="ob-2")
    fetched = approvals.get(apr.approval_id)
    assert fetched is not None
    assert fetched.consumed is False


def test_audit_event_appended(conn) -> None:
    event_id = append_audit(
        conn,
        session_id="sess-1",
        attempt_id="att-1",
        action_type="browser_click",
        error_code=None,
        evidence_ids=["ev-1", "ev-2"],
        actor="mcp",
    )
    assert event_id.startswith("aud-")
    row = conn.execute(
        "SELECT action_type, actor FROM audit_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert row == ("browser_click", "mcp")
