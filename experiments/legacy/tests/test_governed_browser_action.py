"""End-to-end approval claim and signed browser-write coordination."""

from __future__ import annotations

from pathlib import Path

import pytest

from webauto.agent_backends import BrowserAgentSecurityPolicy, BrowserWriteGrantAuthority
from webauto.application import Actor, ApplicationService, Role
from webauto.application.browser_agent import BrowserAgentCoordinator
from webauto.application.settings import RuntimeConfigStore
from webauto.application.vertical_workflows import SHOPPING_WORKSPACES, VerticalWorkflowService
from webauto.domain import AgentTaskResult, AgentTaskStatus, Placement


class ObservedWriteBackend:
    name = "observed-write"

    def __init__(self, authority: BrowserWriteGrantAuthority) -> None:
        self.authority = authority
        self.requests = []

    async def run(self, request, session):
        self.requests.append(request)
        self.authority.consume(request, observed_operation="add_to_cart")
        source = request.context["urls"][0]
        return AgentTaskResult(
            status=AgentTaskStatus.SUCCEEDED,
            verified=True,
            output={"final_result": "cart contains item", "backend_validated": True},
            visited_urls=[source],
            evidence_ids=[source],
        )

    async def pause(self, run_id: str) -> None:
        return None

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        return None

    async def cancel(self, run_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_coordinator_executes_only_claimed_consumed_action_once(
    tmp_path: Path,
) -> None:
    actor = Actor("local-user", "local", {Role.ADMIN})
    application = ApplicationService()
    goal = await application.create_goal(
        actor, objective="collect product", success_criteria=["product collected"]
    )
    source = await application.create_run(
        actor,
        goal_id=goal.id,
        plan_id="source",
        placement=Placement.DESKTOP_MANAGED,
        profile_id="personal",
    )
    await application.start_run(actor, source.id)
    workflows = VerticalWorkflowService(application)
    workspace = await workflows.create_shopping_workspace(
        actor,
        source_run_id=source.id,
        message="买一个鼠标预算200",
        candidates=[
            {
                "platform": "jd",
                "item_id": "mouse-1",
                "title": "无线鼠标",
                "url": "https://item.jd.com/mouse-1.html",
                "price": "129",
                "shipping": 0,
                "in_stock": True,
            }
        ],
    )
    prepared = await workflows.prepare_action(
        actor,
        workspace_category=SHOPPING_WORKSPACES,
        workspace_id=workspace["id"],
        operation="add_to_cart",
        object_scope={"candidate_key": "jd:mouse-1"},
        preview={
            "title": "无线鼠标",
            "total": "129",
            "button_text": "加入购物车",
        },
        page_revision="mouse-page-1",
        evidence_ids=["mouse-shot-1"],
        source_url="https://item.jd.com/mouse-1.html",
        allowed_domains=["item.jd.com"],
    )
    await application.approve(actor, prepared["approval_id"])
    consumed = await workflows.consume_action(actor, prepared["id"])
    action = {**consumed["action"], "approval_id": consumed["approval_id"]}

    authority = BrowserWriteGrantAuthority(b"z" * 32)
    backend = ObservedWriteBackend(authority)
    coordinator = BrowserAgentCoordinator(
        backend,
        RuntimeConfigStore(tmp_path / "var"),
        security_policy=BrowserAgentSecurityPolicy(authority),
        application=application,
    )
    instruction = {
        **consumed,
        "action": action,
        "allowed_domains": consumed["allowed_domains"],
        "available_files": [],
    }
    action_run = await application.get_run(actor, consumed["action_run_id"])

    result = await coordinator.execute_governed_action(actor, action_run, instruction)
    assert result.status == "succeeded"
    assert backend.requests[0].budget.max_external_writes == 1

    second = await coordinator.execute_governed_action(actor, action_run, instruction)
    assert second.status == "failed"
    assert "already claimed" in (second.error or "")
