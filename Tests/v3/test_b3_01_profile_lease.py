"""B3-01 cross-process profile Lease: TTL + fencing + takeover-after-expire."""

from __future__ import annotations

import sqlite3
import tempfile
import time

import pytest

from webauto.storage.sqlite.db import open_db
from webauto.storage.sqlite.repos import LeaseRepo


@pytest.fixture
def conn() -> sqlite3.Connection:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = open_db(f.name)
    yield db
    db.close()


def test_acquire_succeeds_when_empty(conn: sqlite3.Connection) -> None:
    lease = LeaseRepo(conn, ttl_ms=60_000)
    row = lease.acquire("personal", "mcp-1")
    assert row is not None
    assert row.holder_id == "mcp-1"
    assert row.fencing_token.startswith("ft-")


def test_acquire_rejected_while_alive(conn: sqlite3.Connection) -> None:
    lease = LeaseRepo(conn, ttl_ms=60_000)
    assert lease.acquire("personal", "mcp-1") is not None
    assert lease.acquire("personal", "mcp-2") is None


def test_renew_only_for_current_holder(conn: sqlite3.Connection) -> None:
    lease = LeaseRepo(conn, ttl_ms=60_000)
    a = lease.acquire("personal", "mcp-1")
    assert a is not None
    assert lease.renew("personal", "mcp-2") is None
    assert lease.renew("personal", "mcp-1") is not None


def test_takeover_after_expiry(conn: sqlite3.Connection) -> None:
    """Plan §17.3 B3-01: kill -9 / process death → TTL expires → reclaim."""
    lease = LeaseRepo(conn, ttl_ms=50)
    a = lease.acquire("personal", "mcp-1")
    assert a is not None
    time.sleep(0.1)  # 100 ms > 50 ms TTL
    # First mcp-1's lease is now expired; mcp-2 may reclaim.
    fresh = lease.acquire("personal", "mcp-2")
    assert fresh is not None
    assert fresh.holder_id == "mcp-2"
    assert fresh.fencing_token != a.fencing_token


def test_release_only_holder(conn: sqlite3.Connection) -> None:
    lease = LeaseRepo(conn, ttl_ms=60_000)
    assert lease.acquire("personal", "mcp-1") is not None
    # Other holder cannot release.
    assert lease.release("personal", "mcp-2") is False
    # Current holder can.
    assert lease.release("personal", "mcp-1") is True
    assert lease.get("personal") is None


def test_fencing_token_changes_on_takeover(conn: sqlite3.Connection) -> None:
    lease = LeaseRepo(conn, ttl_ms=30)
    a = lease.acquire("personal", "mcp-1")
    assert a is not None
    time.sleep(0.05)
    b = lease.acquire("personal", "mcp-2")
    assert b is not None
    assert b.fencing_token != a.fencing_token
