"""Stable application boundary for replaceable dynamic browser agents."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from webauto.domain.agent_tasks import AgentTaskRequest, AgentTaskResult
from webauto.runtime.browser.session_bridge import BrowserAgentSessionPlan


@runtime_checkable
class BrowserAgentBackend(Protocol):
    name: str

    async def run(
        self, request: AgentTaskRequest, session: BrowserAgentSessionPlan
    ) -> AgentTaskResult: ...

    async def pause(self, run_id: str) -> None: ...

    async def resume(self, run_id: str, user_input: str | None = None) -> None: ...

    async def cancel(self, run_id: str) -> None: ...
