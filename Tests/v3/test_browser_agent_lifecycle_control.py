"""Runtime controls must reach the active dynamic-browser backend."""

from __future__ import annotations

import pytest

from webauto.application.browser_agent import BrowserAgentCoordinator
from webauto.application.settings import RuntimeConfigStore


class ControlledBackend:
    name = "controlled"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def run(self, request, session):  # pragma: no cover - not used here
        raise AssertionError("run should not be called")

    async def pause(self, run_id: str) -> None:
        self.calls.append(("pause", run_id, None))

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        self.calls.append(("resume", run_id, user_input))

    async def cancel(self, run_id: str) -> None:
        self.calls.append(("cancel", run_id, None))


@pytest.mark.asyncio
async def test_coordinator_forwards_pause_resume_and_cancel(tmp_path) -> None:
    backend = ControlledBackend()
    coordinator = BrowserAgentCoordinator(backend, RuntimeConfigStore(tmp_path / "var"))

    await coordinator.pause("run-1")
    await coordinator.resume("run-1", "登录已完成")
    await coordinator.cancel("run-1")

    assert backend.calls == [
        ("pause", "run-1", None),
        ("resume", "run-1", "登录已完成"),
        ("cancel", "run-1", None),
    ]
