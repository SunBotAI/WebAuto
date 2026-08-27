"""B3-03 human takeover / return_control: agent actions paused while human drives."""

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
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    yield


def _seed_lease(session_id: str) -> LeaseRepo:
    conn = open_db(Path(tempfile.gettempdir()) / "webauto-governed" / f"{session_id}.db")
    return LeaseRepo(conn, ttl_ms=60_000)


def test_takeover_then_execute_blocked(isolated_session) -> None:
    g = GovernedActions("sess-take-A")
    _seed_lease("sess-take-A").acquire("personal", "sess-take-A")
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-take-A",
        page_revision="rev-take-A",
        target={"url": "https://example.test/p"},
        content_digest="sha256:take-A",
    )
    # Before takeover: execute with correct fencing token would succeed.
    takeover = g.takeover()
    assert takeover == {"status": "takeover", "control_owner": "human"}

    # After takeover, execute must be blocked even with the right binding.
    lease = _seed_lease("sess-take-A").get("personal")
    result = asyncio.run(
        g.execute(prep.approval_id,
                  expected_object_digest=prep.object_digest,
                  fencing_token=lease.fencing_token)
    )
    assert result["status"] == "blocked"
    assert "CONTROL_OWNED_BY_HUMAN" in result["reason"]
    # Approval must still be unconsumed while blocked.
    assert g.get(prep.approval_id)["consumed"] is False


def test_return_control_resumes_agent_actions(isolated_session) -> None:
    g = GovernedActions("sess-take-B")
    _seed_lease("sess-take-B").acquire("personal", "sess-take-B")
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-take-B",
        page_revision="rev-take-B",
        target={"url": "https://example.test/p"},
        content_digest="sha256:take-B",
    )
    g.takeover()
    assert g.return_control() == {"status": "returned", "control_owner": None}
    # Agent can now execute with a fresh fencing token from the same lease.
    lease = _seed_lease("sess-take-B").get("personal")
    assert lease is not None
    result = asyncio.run(
        g.execute(prep.approval_id,
                  expected_object_digest=prep.object_digest,
                  fencing_token=lease.fencing_token)
    )
    assert result["status"] == "succeeded"


def test_takeover_returns_three_states(isolated_session) -> None:
    """Plan §17.3 B3-03: takeover/return has 3 observable states."""
    g = GovernedActions("sess-take-C")

    # State 1: idle (no human)
    assert g._control_owner is None

    # State 2: taken over
    g.takeover()
    assert g._control_owner == "human"

    # State 3: returned to Agent
    g.return_control()
    assert g._control_owner is None


def test_agent_tools_include_human_takeover_and_return_control() -> None:
    from webauto.application.mcp import list_agent_tools

    names = {t["name"] for t in list_agent_tools()}
    assert "human_takeover" in names
    assert "human_return_control" in names
