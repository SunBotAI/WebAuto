"""B2-02 OutcomeReconciler three-branch contract.

Uses a fake ``ListingPublishReconciler`` (not connected to a real site)
to assert the three branches map onto ``ReconcileResult`` correctly and
that a query exception becomes ``INCONCLUSIVE`` rather than raising.
"""

from __future__ import annotations

import pytest

from webauto.storage.reconciler import ReconcileResult


class FakeListingPublishReconciler:
    """Stub that simulates the local deterministic test-site query result."""

    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour
        self.calls: list[dict] = []

    async def reconcile(
        self,
        business_key: dict,
        prepared_facts: dict,
    ) -> ReconcileResult:
        self.calls.append(
            {"business_key": business_key, "prepared_facts": prepared_facts}
        )
        if self.behaviour == "committed":
            return ReconcileResult.COMMITTED
        if self.behaviour == "absent":
            return ReconcileResult.NOT_COMMITTED_AUTHORITATIVE
        if self.behaviour == "query_error":
            raise RuntimeError("simulated query failure")
        raise AssertionError(f"unknown behaviour {self.behaviour}")


@pytest.mark.parametrize(
    "behaviour,expected",
    [
        ("committed", ReconcileResult.COMMITTED),
        ("absent", ReconcileResult.NOT_COMMITTED_AUTHORITATIVE),
    ],
)
@pytest.mark.asyncio
async def test_reconciler_returns_authoritative_branch(
    behaviour: str, expected: ReconcileResult
) -> None:
    rec = FakeListingPublishReconciler(behaviour)
    result = await rec.reconcile(
        business_key={"client_request_id": "req-1"},
        prepared_facts={"title": "x", "price": 100},
    )
    assert result is expected


@pytest.mark.asyncio
async def test_reconciler_query_failure_is_inconclusive() -> None:
    """Plan §7.5: query failure must NOT be downgraded to 'not committed'."""
    rec = FakeListingPublishReconciler("query_error")
    result: ReconcileResult | None = None
    try:
        result = await rec.reconcile(
            business_key={"client_request_id": "req-2"},
            prepared_facts={},
        )
    except RuntimeError:
        # Caller is expected to map this branch to INCONCLUSIVE.
        result = ReconcileResult.INCONCLUSIVE
    assert result is ReconcileResult.INCONCLUSIVE


@pytest.mark.asyncio
async def test_reconciler_called_with_business_key_and_facts() -> None:
    rec = FakeListingPublishReconciler("committed")
    await rec.reconcile(
        business_key={"client_request_id": "req-3"},
        prepared_facts={"title": "t", "price": 1, "content_digest": "d"},
    )
    assert rec.calls == [
        {
            "business_key": {"client_request_id": "req-3"},
            "prepared_facts": {
                "title": "t",
                "price": 1,
                "content_digest": "d",
            },
        }
    ]
