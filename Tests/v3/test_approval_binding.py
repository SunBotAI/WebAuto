"""Object-level approval binding and non-idempotent commit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from webauto.agent import CommitGuard, CommitState
from webauto.domain import (
    Action,
    ActionKind,
    ApprovalState,
    IdempotencyClass,
    Placement,
    RiskLevel,
    VerifierSpec,
)
from webauto.runtime.reliability import ApprovalService


def publish_action() -> Action:
    return Action(
        kind=ActionKind.CLICK,
        target={"selector": "#publish", "item_id": "item-1"},
        preconditions=["preview_confirmed"],
        risk_level=RiskLevel.L3,
        idempotency=IdempotencyClass.NON_IDEMPOTENT,
        verifier=VerifierSpec(kind="business_query", expectation={"published": True}),
        approval_id="approval-binding",
    )


def test_approval_invalidates_on_page_evidence_or_object_change_and_consumes_once() -> None:
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    service = ApprovalService(clock=lambda: now)
    action = publish_action()
    binding = {
        "page_revision": "page-rev-1",
        "evidence_ids": ["screenshot-1", "dom-1"],
        "object_scope": {"item_id": "item-1", "price": "99.00"},
    }
    pending = service.request(
        run_id="run-1",
        step_id="publish",
        action=action,
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        preview={"title": "approved item", "price": "99.00"},
        diff={"state": {"before": "draft", "after": "published"}},
        ttl=timedelta(minutes=5),
        **binding,
    )
    service.approve(pending.id, "local-user")

    assert service.validate(
        pending.id,
        action,
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        **binding,
    )
    assert not service.validate(
        pending.id,
        action,
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        **{**binding, "page_revision": "page-rev-2"},
    )
    assert not service.validate(
        pending.id,
        action,
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        **{**binding, "evidence_ids": ["attacker-evidence"]},
    )
    assert not service.validate(
        pending.id,
        action,
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        **{**binding, "object_scope": {"item_id": "item-2", "price": "99.00"}},
    )

    consumed = service.consume(
        pending.id,
        action,
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        **binding,
    )
    assert consumed.state == ApprovalState.CONSUMED
    with pytest.raises(RuntimeError, match="already consumed"):
        service.consume(
            pending.id,
            action,
            profile_id="personal",
            placement=Placement.DESKTOP_MANAGED,
            **binding,
        )


def test_uncertain_non_idempotent_commit_requires_query_and_new_approval() -> None:
    guard = CommitGuard(IdempotencyClass.NON_IDEMPOTENT, "approval-1")
    guard.begin_submit()
    guard.mark_transport_unknown()
    with pytest.raises(RuntimeError, match="query"):
        guard.begin_submit()

    guard.record_query(found=False)
    assert guard.state == CommitState.REAPPROVAL_REQUIRED
    with pytest.raises(ValueError, match="new approval"):
        guard.reapprove("approval-1")
    guard.reapprove("approval-2")
    assert guard.state == CommitState.READY
