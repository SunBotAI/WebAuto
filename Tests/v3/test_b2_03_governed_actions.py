"""B2-03 governed_action_prepare / get / execute round-trip.

Asserts the SHA-256 binding semantics: prepare binds payload + page revision
+ identity; get returns the binding; execute consumes the binding
atomically and rejects if the page revision drifts.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from webauto.application.governed_actions import GovernedActions
from webauto.storage.reconciler import ReconcileResult


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    # Clean stale tmpdb so per-test idempotency keys don't collide
    gov_dir = Path(tempfile.gettempdir()) / "webauto-governed"
    if gov_dir.exists():
        shutil.rmtree(gov_dir, ignore_errors=True)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    return "sess-v33-" + tempfile.mkdtemp(dir=tmp_path).rsplit("/", 1)[-1]


def test_prepare_binds_hash_and_returns_approval(session: str) -> None:
    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-1",
        page_revision="rev-A",
        target={"url": "https://example.test/post", "fields": ["title", "price"]},
        content_digest="sha256:content-1",
        identity_digest="id-user-1",
    )
    assert prep.approval_id.startswith("apr-")
    assert prep.attempt_id.startswith("att-")
    assert len(prep.action_hash) == 64
    assert len(prep.object_digest) == 64
    assert prep.policy_version == "v3.3"

    fetched = g.get(prep.approval_id)
    assert fetched is not None
    assert fetched["action_hash"] == prep.action_hash
    assert fetched["page_revision"] == "rev-A"
    assert fetched["consumed"] is False


def test_execute_succeeds_with_matching_digest(session: str) -> None:
    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-2",
        page_revision="rev-B",
        target={"url": "https://example.test/p", "fields": ["title"]},
        content_digest="sha256:content-2",
    )
    assert g._approvals.approve(prep.approval_id)
    result = asyncio.run(
        g.execute(prep.approval_id, expected_object_digest=prep.object_digest)
    )
    assert result["status"] == "succeeded"
    assert result["approval_id"] == prep.approval_id
    # Consumed + resolved
    assert g.get(prep.approval_id)["consumed"] is True
    assert g.get(prep.approval_id)["resolved"] is True


def test_execute_rejects_object_drift(session: str) -> None:
    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-3",
        page_revision="rev-C",
        target={"url": "https://example.test/p", "fields": ["title"]},
        content_digest="sha256:content-3",
    )
    assert g._approvals.approve(prep.approval_id)
    result = asyncio.run(
        g.execute(prep.approval_id, expected_object_digest="sha256:different")
    )
    assert result["status"] == "rejected"
    # Approval must still be unconsumed
    assert g.get(prep.approval_id)["consumed"] is False


def test_execute_twice_only_first_succeeds(session: str) -> None:
    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-4",
        page_revision="rev-D",
        target={"url": "https://example.test/p", "fields": ["title"]},
        content_digest="sha256:content-4",
    )
    assert g._approvals.approve(prep.approval_id)
    first = asyncio.run(
        g.execute(prep.approval_id, expected_object_digest=prep.object_digest)
    )
    assert first["status"] == "succeeded"
    # Second execute on the same approval must fail (already consumed)
    with pytest.raises(RuntimeError, match="already consumed"):
        asyncio.run(
            g.execute(prep.approval_id, expected_object_digest=prep.object_digest)
        )


def test_execute_with_reconciler_returns_branch(session: str) -> None:
    class _Rec:
        async def reconcile(self, business_key, prepared_facts):
            return ReconcileResult.COMMITTED

    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-5",
        page_revision="rev-E",
        target={"url": "https://example.test/p"},
        content_digest="sha256:content-5",
    )
    assert g._approvals.approve(prep.approval_id)
    result = asyncio.run(
        g.execute(prep.approval_id,
                  expected_object_digest=prep.object_digest,
                  reconciler=_Rec())
    )
    assert result["status"] == "succeeded"
    assert result["reconcile"] == "committed"


def test_prepare_is_run_id_independent(session: str) -> None:
    """B2-03: prepare/execute must work without any run_id or Vertical."""
    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-6",
        page_revision="rev-F",
        target={"url": "https://example.test/x"},
        content_digest="sha256:content-6",
    )
    # No run_id passed in; only client_request_id + target + digests.
    assert prep.attempt_id.startswith("att-")
    assert prep.approval_id.startswith("apr-")


def test_execute_requires_explicit_approval_and_reject_is_terminal(session: str) -> None:
    g = GovernedActions(session)
    prep = g.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-approval-gate",
        page_revision="rev-gate",
        target={"url": "https://example.test/p"},
        content_digest="sha256:gate",
    )
    blocked = asyncio.run(
        g.execute(prep.approval_id, expected_object_digest=prep.object_digest)
    )
    assert blocked["status"] == "rejected"
    assert g._approvals.reject(prep.approval_id)
    assert not g._approvals.approve(prep.approval_id)
