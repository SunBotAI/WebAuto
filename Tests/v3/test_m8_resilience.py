"""M8 fault injection, approval/idempotency attacks and privacy tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from webauto.agent import (
    CommitGuard,
    FallbackChain,
    FallbackModelProvider,
    ModelRequest,
    RecoveryExhausted,
)
from webauto.domain import (
    Action,
    ActionKind,
    IdempotencyClass,
    PageState,
    Placement,
    RiskLevel,
    VerifierSpec,
)
from webauto.runtime.artifact_store import SecureArtifactStore
from webauto.runtime.browser.grounder import GroundingTarget, PageStateGrounder
from webauto.runtime.reliability import ApprovalService, InMemoryIdempotencyStore

APPROVAL_BINDING = {
    "page_revision": "page-rev-1",
    "evidence_ids": ["evidence-1"],
    "object_scope": {"item_id": "item-1"},
}


def critical_action(item_id="item-1"):
    return Action(
        kind=ActionKind.CLICK,
        target={"selector": "#submit", "item_id": item_id},
        preconditions=["preview_confirmed"],
        risk_level=RiskLevel.L3,
        idempotency=IdempotencyClass.NON_IDEMPOTENT,
        verifier=VerifierSpec(kind="business_query", expectation={"item_id": item_id}),
        approval_id="pending",
    )


def test_old_approval_wrong_item_account_or_placement_is_rejected() -> None:
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    approvals = ApprovalService(clock=lambda: now)
    action = critical_action()
    approval = approvals.request(
        run_id="run-1",
        step_id="step-1",
        action=action,
        profile_id="account-1",
        placement=Placement.DESKTOP_MANAGED,
        preview={},
        diff={},
        ttl=timedelta(minutes=5),
        **APPROVAL_BINDING,
    )
    approvals.approve(approval.id, "user-1")
    assert approvals.validate(
        approval.id,
        action,
        profile_id="account-1",
        placement=Placement.DESKTOP_MANAGED,
        **APPROVAL_BINDING,
    )
    assert not approvals.validate(
        approval.id,
        critical_action("item-2"),
        profile_id="account-1",
        placement=Placement.DESKTOP_MANAGED,
        **APPROVAL_BINDING,
    )
    assert not approvals.validate(
        approval.id,
        action,
        profile_id="account-2",
        placement=Placement.DESKTOP_MANAGED,
        **APPROVAL_BINDING,
    )
    assert not approvals.validate(
        approval.id,
        action,
        profile_id="account-1",
        placement=Placement.BROWSER_ATTACH,
        **APPROVAL_BINDING,
    )


def test_unknown_non_idempotent_submit_cannot_be_retried_blindly() -> None:
    guard = CommitGuard(IdempotencyClass.NON_IDEMPOTENT, "approval-1")
    guard.begin_submit()
    guard.mark_transport_unknown()
    with pytest.raises(RuntimeError, match="query"):
        guard.begin_submit()


class AlwaysFailModel:
    def __init__(self, name):
        self.name = name

    async def complete(self, request):
        raise TimeoutError(self.name)


@pytest.mark.asyncio
async def test_all_model_failures_stop_instead_of_bypassing_policy() -> None:
    provider = FallbackModelProvider([AlwaysFailModel("one"), AlwaysFailModel("two")])
    with pytest.raises(RuntimeError, match="all model providers failed"):
        await provider.complete(ModelRequest(task="plan", payload={}))
    assert provider.attempts == (("one", "timeout"), ("two", "timeout"))


def test_selector_and_page_change_exhaust_bounded_recovery() -> None:
    state = PageState(url="https://example.test/changed", dom_snapshot="<main>new layout</main>")
    assert PageStateGrounder().ground(GroundingTarget(name="旧按钮", role="button"), state) == []
    chain = FallbackChain(max_recoveries=2)
    chain.next()
    chain.next()
    with pytest.raises(RecoveryExhausted):
        chain.next()


@pytest.mark.asyncio
async def test_artifact_redaction_and_owner_check_prevent_cross_tenant_secret_leak(
    tmp_path: Path,
) -> None:
    store = SecureArtifactStore(tmp_path)
    record = await store.put(
        owner_id="tenant-1",
        content=b"Authorization: Bearer secret-token",
        media_type="text/plain",
        retention=timedelta(minutes=5),
        redact=lambda value: value.replace(b"secret-token", b"<redacted>"),
    )
    content = await store.get(record.id, owner_id="tenant-1")
    assert b"secret-token" not in content
    with pytest.raises(PermissionError):
        await store.get(record.id, owner_id="tenant-2")


@pytest.mark.asyncio
async def test_shared_idempotency_fact_survives_worker_object_restart() -> None:
    durable = InMemoryIdempotencyStore()
    assert await durable.claim("run-1:step-1:action-1")
    await durable.complete("run-1:step-1:action-1", {"status": "confirmed"})
    # A new worker receives the same durable store and cannot claim the action again.
    assert not await durable.claim("run-1:step-1:action-1")
    assert (await durable.result("run-1:step-1:action-1"))["status"] == "confirmed"
