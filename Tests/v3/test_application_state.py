"""ApplicationService restart durability and state-store contract tests."""

from datetime import timedelta

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.state import InMemoryApplicationStateStore, JsonApplicationStateStore
from webauto.config import SecretValue
from webauto.domain import (
    Action,
    ActionKind,
    IdempotencyClass,
    Placement,
    RiskLevel,
    VerifierSpec,
)
from webauto.storage.application_state import PostgresApplicationStateStore


def operator() -> Actor:
    return Actor("operator", "tenant-1", {Role.OPERATOR})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "json"])
async def test_service_restart_restores_run_approval_resource_and_audit(tmp_path, kind) -> None:
    store = (
        InMemoryApplicationStateStore()
        if kind == "memory"
        else JsonApplicationStateStore(tmp_path / "application-state.json")
    )
    first = ApplicationService(state_store=store)
    owner = operator()
    goal = await first.create_goal(
        owner, objective="准备授权商品草稿", success_criteria=["发布前已复核"]
    )
    run = await first.create_run(
        owner,
        goal_id=goal.id,
        plan_id="plan-1",
        placement=Placement.DESKTOP_MANAGED,
        profile_id="profile-1",
    )
    await first.upsert_resource(owner, "profiles", "profile-1", {"login_health": "ok"})
    approval = await first.request_approval(
        owner,
        run_id=run.id,
        step_id="step-1",
        action=Action(
            kind=ActionKind.CLICK,
            target={"selector": "#publish"},
            preconditions=["preview_confirmed"],
            risk_level=RiskLevel.L3,
            idempotency=IdempotencyClass.NON_IDEMPOTENT,
            verifier=VerifierSpec(kind="business_query", expectation={"published": True}),
            approval_id="pending",
        ),
        preview={"title": "商品"},
        diff={"status": {"before": "draft", "after": "published"}},
        page_revision="page-rev-1",
        evidence_ids=["evidence-1"],
        object_scope={"item_id": "item-1"},
        ttl=timedelta(minutes=5),
    )

    restarted = ApplicationService(state_store=store)
    assert (await restarted.get_run(owner, run.id)).goal_id == goal.id
    assert (await restarted.list_resources(owner, "profiles"))["profile-1"]["login_health"] == "ok"
    approvals = await restarted.list_approvals(Actor("approver", "tenant-1", {Role.APPROVER}))
    assert approvals[0].id == approval.id
    assert [item.action for item in restarted.audit_log] == [
        "goal.create",
        "run.create",
        "profiles.upsert",
        "approval.request",
    ]


@pytest.mark.asyncio
async def test_json_store_rejects_unknown_snapshot_schema(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"schema_version":"999"}', encoding="utf-8")
    service = ApplicationService(state_store=JsonApplicationStateStore(path))
    with pytest.raises(RuntimeError, match="unsupported application-state schema"):
        await service.list_resources(operator(), "profiles")


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def execute(self, sql, parameters=None):
        self.statements.append((sql, parameters))
        return _Cursor(self.row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        self.closes += 1


@pytest.mark.asyncio
async def test_postgres_state_store_loads_then_saves_with_revision_guard() -> None:
    loading = _Connection(None)
    saving = _Connection((1,))
    connections = iter([loading, saving])

    async def connect(dsn):
        assert dsn == "postgresql://user:secret@localhost/webauto"
        return next(connections)

    store = PostgresApplicationStateStore(
        SecretValue("postgresql://user:secret@localhost/webauto"), connect=connect
    )
    assert await store.load() is None
    await store.save({"schema_version": "1"})
    assert "select revision" in loading.statements[0][0].lower()
    assert "on conflict" in saving.statements[0][0].lower()
    assert saving.commits == 1
    assert loading.closes == saving.closes == 1
