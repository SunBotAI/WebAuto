"""Approval inbox, run detail, resources and legacy adapter tests."""

from datetime import timedelta

import pytest

from webauto.application import Actor, ApplicationService, PermissionDenied, Role
from webauto.application.adapters import CliAdapter, McpAdapter, WebAdapter
from webauto.domain import (
    Action,
    ActionKind,
    ApprovalState,
    IdempotencyClass,
    Placement,
    RiskLevel,
    VerifierSpec,
)


def operator(tenant="tenant-1"):
    return Actor("operator", tenant, {Role.OPERATOR})


def approver(tenant="tenant-1"):
    return Actor("approver", tenant, {Role.APPROVER})


def publish_action():
    return Action(
        kind=ActionKind.CLICK,
        target={"selector": "#publish"},
        preconditions=["preview_confirmed"],
        risk_level=RiskLevel.L3,
        idempotency=IdempotencyClass.NON_IDEMPOTENT,
        verifier=VerifierSpec(kind="business_query", expectation={"published": True}),
        approval_id="pending",
    )


@pytest.mark.asyncio
async def test_approval_inbox_approve_reject_revoke_and_tenant_isolation() -> None:
    service = ApplicationService()
    owner = operator()
    goal = await service.create_goal(
        owner, objective="准备已确认内容并请求发布", success_criteria=["发布状态已查询"]
    )
    run = await service.create_run(
        owner,
        goal_id=goal.id,
        plan_id="plan-1",
        placement=Placement.DESKTOP_MANAGED,
        profile_id="profile-1",
    )
    approval = await service.request_approval(
        owner,
        run_id=run.id,
        step_id="step-1",
        action=publish_action(),
        preview={"title": "商品"},
        diff={"status": {"before": "draft", "after": "published"}},
        page_revision="page-rev-1",
        evidence_ids=["evidence-1"],
        object_scope={"item_id": "item-1"},
        ttl=timedelta(minutes=5),
    )
    approved = await service.approve(approver(), approval.id)
    assert approved.state == ApprovalState.APPROVED
    assert (await service.list_approvals(approver()))[0].diff

    with pytest.raises(PermissionDenied):
        await service.approve(approver("tenant-2"), approval.id)

    revoked = await service.revoke_approval(approver(), approval.id)
    assert revoked.state == ApprovalState.REVOKED


@pytest.mark.asyncio
async def test_run_detail_exposes_candidates_reason_timeline_and_control_state() -> None:
    service = ApplicationService()
    owner = operator()
    goal = await service.create_goal(
        owner, objective="查看授权商品列表并比较", success_criteria=["候选已验证"]
    )
    run = await service.create_run(owner, goal_id=goal.id, plan_id="plan-primary")
    await service.set_plan_view(
        owner,
        run.id,
        candidates=[{"id": "plan-primary", "score": 0.9}, {"id": "plan-fallback", "score": 0.7}],
        selection_reason="site skill has higher verified success rate",
    )
    detail = await service.run_detail(owner, run.id)
    assert detail["run"].id == run.id
    assert len(detail["candidates"]) == 2
    assert "higher" in detail["selection_reason"]
    assert detail["timeline"]


@pytest.mark.asyncio
async def test_profile_node_policy_resources_are_tenant_scoped() -> None:
    service = ApplicationService()
    owner = operator()
    await service.upsert_resource(owner, "profiles", "profile-1", {"login_health": "ok"})
    await service.upsert_resource(owner, "nodes", "node-1", {"online": True})
    await service.upsert_resource(owner, "policies", "default", {"max_autonomous_risk": "L1"})
    assert (await service.list_resources(owner, "profiles"))["profile-1"]["login_health"] == "ok"
    with pytest.raises(PermissionDenied):
        await service.list_resources(operator("tenant-2"), "profiles", resource_ids=["profile-1"])


def test_cli_mcp_and_web_adapters_share_exact_service_instance() -> None:
    service = ApplicationService()
    assert CliAdapter(service).service is service
    assert McpAdapter(service).service is service
    assert WebAdapter(service).service is service
