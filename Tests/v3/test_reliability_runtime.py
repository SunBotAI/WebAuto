"""M4 reliability services: approvals, checkpoints, scheduling and idempotency."""

from datetime import datetime, timedelta, timezone

import pytest

from webauto.domain import (
    Action,
    ActionKind,
    ApprovalState,
    IdempotencyClass,
    PageState,
    Placement,
    RiskLevel,
    VerifierSpec,
)
from webauto.runtime.reliability import (
    ApprovalService,
    Checkpoint,
    InMemoryCheckpointStore,
    InMemoryIdempotencyStore,
    InMemoryScheduler,
    WorkerHeartbeatRegistry,
)

APPROVAL_BINDING = {
    "page_revision": "page-rev-1",
    "evidence_ids": ["evidence-1"],
    "object_scope": {"item_id": "item-1"},
}


def write_action() -> Action:
    return Action(
        kind=ActionKind.CLICK,
        target={"selector": "#publish"},
        preconditions=["preview_confirmed"],
        risk_level=RiskLevel.L3,
        idempotency=IdempotencyClass.NON_IDEMPOTENT,
        verifier=VerifierSpec(kind="business_query", expectation={"published": True}),
        approval_id="pending-binding",
    )


def test_approval_service_binds_exact_action_profile_placement_and_expiry() -> None:
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    service = ApprovalService(clock=lambda: now)
    action = write_action()
    pending = service.request(
        run_id="run-1",
        step_id="step-1",
        action=action,
        profile_id="profile-1",
        placement=Placement.DESKTOP_MANAGED,
        preview={"title": "商品"},
        diff={"price": {"before": None, "after": "99"}},
        **APPROVAL_BINDING,
        ttl=timedelta(minutes=5),
    )
    approved = service.approve(pending.id, resolved_by="user-1")
    assert approved.state == ApprovalState.APPROVED
    assert service.validate(
        approved.id,
        action,
        profile_id="profile-1",
        placement=Placement.DESKTOP_MANAGED,
        **APPROVAL_BINDING,
    )
    assert not service.validate(
        approved.id,
        action,
        profile_id="profile-1",
        placement=Placement.BROWSER_ATTACH,
        **APPROVAL_BINDING,
    )


def test_revoked_approval_is_not_valid() -> None:
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    service = ApprovalService(clock=lambda: now)
    pending = service.request(
        run_id="run-1",
        step_id=None,
        action=write_action(),
        profile_id="profile-1",
        placement=Placement.DESKTOP_MANAGED,
        preview={},
        diff={},
        **APPROVAL_BINDING,
        ttl=timedelta(minutes=5),
    )
    service.approve(pending.id, "user-1")
    revoked = service.revoke(pending.id, "user-1")
    assert revoked.state == ApprovalState.REVOKED


@pytest.mark.asyncio
async def test_checkpoint_round_trip_preserves_verified_facts_and_resume_node() -> None:
    store = InMemoryCheckpointStore()
    checkpoint = Checkpoint(
        run_id="run-1",
        plan_id="plan-1",
        plan_version="1.0",
        resume_node_id="verify",
        verified_facts={"draft_saved": True},
        page_state=PageState(url="https://example.test/draft"),
    )
    await store.save(checkpoint)
    assert await store.latest("run-1") == checkpoint


def test_scheduler_deduplicates_and_applies_misfire_policy() -> None:
    now = datetime(2026, 8, 21, 10, tzinfo=timezone.utc)
    scheduler = InMemoryScheduler(clock=lambda: now)
    first = scheduler.schedule("job-key", now - timedelta(minutes=1), {"goal_id": "g1"})
    second = scheduler.schedule("job-key", now, {"goal_id": "g1"})
    assert first.id == second.id
    due = scheduler.due(misfire_grace=timedelta(minutes=2))
    assert [job.id for job in due] == [first.id]
    assert scheduler.due(misfire_grace=timedelta(minutes=2)) == ()


@pytest.mark.asyncio
async def test_idempotency_store_claims_once_and_records_result() -> None:
    store = InMemoryIdempotencyStore()
    assert await store.claim("run:step:action")
    assert not await store.claim("run:step:action")
    await store.complete("run:step:action", {"status": "ok"})
    assert await store.result("run:step:action") == {"status": "ok"}


def test_heartbeat_reaper_finds_stale_workers() -> None:
    now = datetime(2026, 8, 21, 10, tzinfo=timezone.utc)
    registry = WorkerHeartbeatRegistry(clock=lambda: now)
    registry.beat("worker-old", observed_at=now - timedelta(minutes=5))
    registry.beat("worker-new", observed_at=now)
    assert registry.stale(timedelta(minutes=1)) == ("worker-old",)
