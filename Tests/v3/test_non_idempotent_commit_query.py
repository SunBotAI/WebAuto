"""Non-idempotent writes query business state instead of retrying."""

from __future__ import annotations

from pathlib import Path

import pytest

from webauto.agent_backends import BrowserAgentSecurityPolicy, BrowserWriteGrantAuthority
from webauto.application import Actor, ApplicationService, Role
from webauto.application.browser_agent import BrowserAgentCoordinator
from webauto.application.settings import RuntimeConfigStore
from webauto.application.vertical_workflows import XIANYU_BUY_WORKSPACES, VerticalWorkflowService
from webauto.domain import AgentTaskResult, AgentTaskStatus, Placement


class UncertainMessageBackend:
    name = "uncertain-message"

    def __init__(self, authority: BrowserWriteGrantAuthority, query_mode: str) -> None:
        self.authority = authority
        self.query_mode = query_mode
        self.requests = []

    async def run(self, request, session):
        self.requests.append(request)
        if not request.read_only:
            self.authority.consume(request, observed_operation="xianyu_send_message")
            return AgentTaskResult(
                status=AgentTaskStatus.FAILED,
                error="transport closed after click",
            )
        criterion = request.success_criteria[0]
        source = "https://www.goofish.com/messages"
        if self.query_mode == "ambiguous":
            return AgentTaskResult(
                status=AgentTaskStatus.PARTIAL,
                output={"final_result": "cannot determine"},
            )
        found = self.query_mode == "found"
        return AgentTaskResult(
            status=AgentTaskStatus.COMPLETED,
            output={
                "final_result": "queried message history",
                "backend_validated": True,
                "criteria": [
                    {
                        "criterion": criterion,
                        "satisfied": found,
                        "evidence_urls": [source],
                        "explanation": "message history was inspected",
                    }
                ],
            },
            facts=[{"claim": "message history inspected", "source_url": source}],
            visited_urls=[source],
            evidence_ids=[source],
        )

    async def pause(self, run_id: str) -> None:
        return None

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        return None

    async def cancel(self, run_id: str) -> None:
        return None


async def approved_inquiry(application: ApplicationService, actor: Actor):
    goal = await application.create_goal(
        actor, objective="inspect item", success_criteria=["inspected"]
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
    workspace = await workflows.create_xianyu_buy_workspace(
        actor,
        source_run_id=source.id,
        item={
            "id": "item-1",
            "title": "二手相机",
            "url": "https://www.goofish.com/item?id=item-1",
            "description": "有正常使用痕迹，具体以图片为准",
            "real_photos": True,
        },
    )
    prepared = await workflows.prepare_action(
        actor,
        workspace_category=XIANYU_BUY_WORKSPACES,
        workspace_id=workspace["id"],
        operation="xianyu_send_message",
        object_scope={},
        preview={"message": "你好，还在吗？", "button_text": "发送"},
        page_revision="message-page-1",
        evidence_ids=["message-shot-1"],
        source_url="https://www.goofish.com/item?id=item-1",
        allowed_domains=["www.goofish.com"],
    )
    await application.approve(actor, prepared["approval_id"])
    consumed = await workflows.consume_action(actor, prepared["id"])
    return consumed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query_mode", "expected_status", "expected_flag"),
    [
        ("found", "succeeded", None),
        ("not_found", "failed", "reapproval_required"),
        ("ambiguous", "waiting_human", "uncertain_commit"),
    ],
)
async def test_non_idempotent_commit_is_queried_without_write_replay(
    tmp_path: Path,
    query_mode: str,
    expected_status: str,
    expected_flag: str | None,
) -> None:
    actor = Actor("local-user", "local", {Role.ADMIN})
    application = ApplicationService()
    consumed = await approved_inquiry(application, actor)
    authority = BrowserWriteGrantAuthority(b"q" * 32)
    backend = UncertainMessageBackend(authority, query_mode)
    coordinator = BrowserAgentCoordinator(
        backend,
        RuntimeConfigStore(tmp_path / "var"),
        security_policy=BrowserAgentSecurityPolicy(authority),
        application=application,
    )
    instruction = {
        **consumed,
        "action": {
            **consumed["action"],
            "approval_id": consumed["approval_id"],
        },
        "available_files": [],
    }
    run = await application.get_run(actor, consumed["action_run_id"])

    result = await coordinator.execute_governed_action(actor, run, instruction)

    assert result.status == expected_status
    assert len(backend.requests) == 2
    assert backend.requests[0].read_only is False
    assert backend.requests[1].read_only is True
    assert backend.requests[1].budget.max_external_writes == 0
    if expected_flag:
        assert result.output[expected_flag] is True
