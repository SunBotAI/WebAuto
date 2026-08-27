"""Conversational entry point backed exclusively by ApplicationService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from webauto.agent import GoalCompiler

from .service import Actor, ApplicationService


@dataclass(frozen=True, slots=True)
class ChatReply:
    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class ButlerChat:
    def __init__(self, service: ApplicationService) -> None:
        self._service = service

    async def handle(
        self,
        actor: Actor,
        message: str,
        *,
        success_criteria: list[str] | None = None,
    ) -> ChatReply:
        criteria = list(success_criteria or [])
        compiled = GoalCompiler().compile(message, success_criteria=criteria)
        if compiled.goal is None:
            return ChatReply(
                "clarification",
                "；".join(compiled.clarifications),
                {"questions": list(compiled.clarifications)},
            )
        goal = await self._service.create_goal(
            actor,
            objective=message,
            success_criteria=criteria,
        )
        return ChatReply(
            "goal_created",
            "目标已创建，请查看计划候选后再启动。",
            {"goal_id": goal.id},
        )
