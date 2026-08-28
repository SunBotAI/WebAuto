"""B3-02 dispatch fencing: stale fencing_token rejects execute."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from webauto.application.governed_actions import GovernedActions
from webauto.storage.sqlite.db import open_db
from webauto.storage.sqlite.repos import LeaseRepo


@pytest.fixture
def isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test TMPDIR + clean stale /tmp/webauto-governed."""
    import shutil
    gov_dir = Path(tempfile.gettempdir()) / "webauto-governed"
    if gov_dir.exists():
        shutil.rmtree(gov_dir, ignore_errors=True)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    yield


def test_dispatch_with_current_fencing_token_succeeds(isolated_session) -> None:
    g = GovernedActions("sess-fence-A")
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-fence-A",
        page_revision="rev-fence-A",
        target={"url": "https://example.test/p"},
        content_digest="sha256:fence-A",
    )
    # Seed a live lease for the session's "personal" profile.
    conn = open_db(Path(tempfile.gettempdir()) / "webauto-governed" / "sess-fence-A.db")
    lease = LeaseRepo(conn, ttl_ms=60_000).acquire("personal", "sess-fence-A")
    assert lease is not None
    assert g._approvals.approve(prep.approval_id)
    result = asyncio.run(
        g.execute(prep.approval_id,
                  expected_object_digest=prep.object_digest,
                  profile_id="personal",
                  holder_id="sess-fence-A",
                  fencing_token=lease.fencing_token)
    )
    assert result["status"] == "succeeded"


def test_dispatch_with_stale_fencing_token_rejected(isolated_session) -> None:
    g = GovernedActions("sess-fence-B")
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-fence-B",
        page_revision="rev-fence-B",
        target={"url": "https://example.test/p"},
        content_digest="sha256:fence-B",
    )
    conn = open_db(Path(tempfile.gettempdir()) / "webauto-governed" / "sess-fence-B.db")
    repo = LeaseRepo(conn, ttl_ms=60_000)
    lease_a = repo.acquire("personal", "sess-fence-B")
    assert lease_a is not None
    # Simulate takeover by another holder after expiry.
    repo._conn.execute(
        "UPDATE profile_leases SET expires_at_ms = 0 WHERE profile_id = ?",
        ("personal",),
    )
    lease_b = repo.acquire("personal", "sess-fence-B-new")
    assert lease_b is not None
    assert lease_b.fencing_token != lease_a.fencing_token
    assert g._approvals.approve(prep.approval_id)

    # Old token must be rejected at dispatch.
    result = asyncio.run(
        g.execute(prep.approval_id,
                  expected_object_digest=prep.object_digest,
                  profile_id="personal",
                  holder_id="sess-fence-B",
                  fencing_token=lease_a.fencing_token)
    )
    assert result["status"] == "rejected"
    assert "fencing_token stale" in result["reason"]
    # Approval must still be unconsumed.
    assert g.get(prep.approval_id)["consumed"] is False
