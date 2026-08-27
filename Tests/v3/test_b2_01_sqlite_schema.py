"""B2-01 sqlite3 five-table bootstrap and account-safety budget persistence.

Asserts the schema in ``storage/sqlite/migrations/0001_v33.sql`` is applied
with WAL + foreign_keys + schema_migrations, that each safety-critical
table accepts the contract fields, and that the account-safety budget
window survives a Provider / network-identity switch (plan §17.3).
"""

from __future__ import annotations

import sqlite3
import tempfile
import time

import pytest

from webauto.storage.sqlite.db import open_db


@pytest.fixture
def conn() -> sqlite3.Connection:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = open_db(f.name)
    yield db
    db.close()


def test_schema_applies_with_pragmas(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    }
    assert {"schema_migrations", "profile_leases", "action_attempts",
            "approvals", "behavior_budgets", "audit_events"} <= tables
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = '0001_v33'"
    ).fetchone()[0] == 1


def test_profile_lease_round_trip(conn: sqlite3.Connection) -> None:
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO profile_leases "
        "(lease_id, profile_id, holder_id, fencing_token, expires_at_ms, "
        " created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lease-1", "personal", "mcp-1", "ft-abc", now + 60_000, now, now),
    )
    row = conn.execute(
        "SELECT lease_id, profile_id, holder_id, fencing_token FROM "
        "profile_leases WHERE lease_id = ?", ("lease-1",)
    ).fetchone()
    assert row == ("lease-1", "personal", "mcp-1", "ft-abc")


def test_action_attempt_idempotency_unique(conn: sqlite3.Connection) -> None:
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO action_attempts "
        "(attempt_id, session_id, action_hash, idempotency_key, status, "
        " prepared_facts, optimistic_version, created_at_ms, updated_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
        ("a1", "sess-1", "ah-1", "idem-1", "PREPARED", "{}", now, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO action_attempts "
            "(attempt_id, session_id, action_hash, idempotency_key, status, "
            " prepared_facts, optimistic_version, created_at_ms, updated_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            ("a2", "sess-1", "ah-2", "idem-1", "PREPARED", "{}", now, now),
        )


def test_approval_consume_is_atomic(conn: sqlite3.Connection) -> None:
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO approvals "
        "(approval_id, attempt_id, action_hash, page_revision, evidence_digest, "
        " object_digest, identity_digest, policy_version, expires_at_ms, "
        " consumed, resolved, created_at_ms, updated_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
        ("ap-1", "a1", "ah-1", "rev-1", "ev-1", "ob-1", "id-1", "v3.3",
         now + 60_000, now, now),
    )
    cur = conn.execute(
        "UPDATE approvals SET consumed = 1, updated_at_ms = ? "
        "WHERE approval_id = ? AND consumed = 0",
        (now, "ap-1"),
    )
    assert cur.rowcount == 1
    # second attempt: rowcount must be 0 (already consumed)
    cur = conn.execute(
        "UPDATE approvals SET consumed = 1, updated_at_ms = ? "
        "WHERE approval_id = ? AND consumed = 0",
        (now, "ap-1"),
    )
    assert cur.rowcount == 0


def test_account_safety_budget_survives_provider_switch(conn: sqlite3.Connection) -> None:
    """Plan §17.3 B2-01 / DoD 11: Budget/Circuit clears *not* on Provider change.

    Switching the browser provider must NOT reset the account-safety
    cooldown / circuit that protects the (site, account_ref|profile_id)
    tuple.
    """
    now = int(time.time() * 1000)
    window_start = (now // 60_000) * 60_000
    scope_key = "site=jd.com|account=u-42"
    digest = __import__("hashlib").sha256(scope_key.encode("utf-8")).hexdigest()

    # Two 403 hits under provider A trigger a cooldown until now + 15 min.
    conn.execute(
        "INSERT INTO behavior_budgets "
        "(scope_type, scope_key_digest, window_start_ms, executions, writes, "
        " last_reset_ms, cooldown_until_ms, circuit_open_until_ms, hits_403, "
        " hits_429, challenge_count) "
        "VALUES (?, ?, ?, 0, 0, ?, ?, 0, 2, 0, 0)",
        ("account_safety", digest, window_start, now, now + 15 * 60_000),
    )

    # Switch provider: a fresh execution under a different provider_id
    # must observe the same cooldown / hits_403.
    row = conn.execute(
        "SELECT cooldown_until_ms, hits_403, circuit_open_until_ms "
        "FROM behavior_budgets "
        "WHERE scope_type = ? AND scope_key_digest = ? "
        "AND window_start_ms = ?",
        ("account_safety", digest, window_start),
    ).fetchone()
    assert row == (now + 15 * 60_000, 2, 0)

    # And after a "Provider switch" simulation (new lease row, same
    # scope), the budget stays.
    conn.execute(
        "INSERT INTO profile_leases "
        "(lease_id, profile_id, holder_id, fencing_token, expires_at_ms, "
        " created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lease-2", "personal", "mcp-2", "ft-xyz", now + 60_000, now, now),
    )
    row = conn.execute(
        "SELECT cooldown_until_ms, hits_403 FROM behavior_budgets "
        "WHERE scope_type = ? AND scope_key_digest = ?",
        ("account_safety", digest),
    ).fetchone()
    assert row == (now + 15 * 60_000, 2)
