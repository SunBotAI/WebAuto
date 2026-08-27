"""M6 application service, RBAC, tenant isolation and event tests."""

import asyncio

import pytest

from webauto.application import (
    Actor,
    ApplicationService,
    EventBroker,
    PermissionDenied,
    Role,
)
from webauto.domain import Placement, RiskBudget, RiskLevel, RunState


def actor(user="user-1", tenant="tenant-1", role=Role.OPERATOR):
    return Actor(user_id=user, tenant_id=tenant, roles={role})


@pytest.mark.asyncio
async def test_application_service_create_start_pause_resume_cancel() -> None:
    service = ApplicationService()
    owner = actor()
    goal = await service.create_goal(
        owner,
        objective="查看授权页面中的商品信息",
        success_criteria=["页面数据已验证"],
        risk_budget=RiskBudget(max_risk=RiskLevel.L1),
    )
    run = await service.create_run(owner, goal_id=goal.id, plan_id="plan-1")
    assert (await service.start_run(owner, run.id)).state == RunState.RUNNING
    assert (await service.pause_run(owner, run.id)).state == RunState.PAUSED
    assert (await service.resume_run(owner, run.id)).state == RunState.RUNNING
    assert (await service.cancel_run(owner, run.id)).state == RunState.CANCELLED
    assert [item.action for item in service.audit_log] == [
        "goal.create",
        "run.create",
        "run.start",
        "run.pause",
        "run.resume",
        "run.cancel",
    ]


@pytest.mark.asyncio
async def test_tenant_cannot_read_or_mutate_another_tenants_run() -> None:
    service = ApplicationService()
    owner = actor()
    goal = await service.create_goal(
        owner, objective="读取授权页面状态", success_criteria=["已验证"]
    )
    run = await service.create_run(owner, goal_id=goal.id, plan_id="plan-1")
    outsider = actor(user="user-2", tenant="tenant-2")
    with pytest.raises(PermissionDenied):
        await service.get_run(outsider, run.id)
    with pytest.raises(PermissionDenied):
        await service.cancel_run(outsider, run.id)


@pytest.mark.asyncio
async def test_viewer_cannot_start_run() -> None:
    service = ApplicationService()
    owner = actor()
    goal = await service.create_goal(
        owner, objective="读取授权页面状态", success_criteria=["已验证"]
    )
    run = await service.create_run(owner, goal_id=goal.id, plan_id="plan-1")
    viewer = actor(user="viewer", tenant="tenant-1", role=Role.VIEWER)
    with pytest.raises(PermissionDenied):
        await service.start_run(viewer, run.id)


@pytest.mark.asyncio
async def test_event_broker_delivers_tenant_scoped_realtime_events() -> None:
    broker = EventBroker()
    subscription = broker.subscribe("tenant-1")
    await broker.publish("tenant-1", "run.updated", {"run_id": "r1"})
    event = await asyncio.wait_for(anext(subscription), timeout=0.1)
    assert event.kind == "run.updated"
    assert event.payload["run_id"] == "r1"
    await subscription.aclose()


@pytest.mark.asyncio
async def test_takeover_and_return_are_audited() -> None:
    service = ApplicationService()
    owner = actor()
    goal = await service.create_goal(
        owner, objective="检查页面并等待人工接管", success_criteria=["已确认"]
    )
    run = await service.create_run(
        owner, goal_id=goal.id, plan_id="plan-1", placement=Placement.DESKTOP_MANAGED
    )
    await service.start_run(owner, run.id)
    assert (await service.takeover(owner, run.id)).state == RunState.WAITING_HUMAN
    assert (await service.return_control(owner, run.id)).state == RunState.RUNNING
    assert service.audit_log[-2].action == "run.takeover"
    assert service.audit_log[-1].action == "run.return_control"
