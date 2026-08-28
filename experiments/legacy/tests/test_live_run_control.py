"""A long Butler request can be paused and resumed before its HTTP reply returns."""

from __future__ import annotations

import asyncio

import pytest

from webauto.application import ApplicationService
from webauto.application.butler_service import ButlerExecutionResult, ButlerService
from webauto.application.control_api import create_app

HEADERS = {
    "x-user-id": "owner",
    "x-tenant-id": "personal",
    "x-roles": "operator",
}


class BlockingBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.run_id: str | None = None
        self.controls: list[str] = []

    async def execute(self, request):
        self.run_id = request.run.id
        self.started.set()
        await self.release.wait()
        return ButlerExecutionResult("succeeded", {"resumed": True})

    async def pause(self, run_id: str) -> None:
        assert run_id == self.run_id
        self.controls.append("pause")

    async def resume(self, run_id: str, user_input: str | None = None) -> None:
        assert run_id == self.run_id
        self.controls.append("resume")
        self.release.set()

    async def cancel(self, run_id: str) -> None:
        self.controls.append("cancel")


@pytest.mark.asyncio
async def test_pending_http_task_can_pause_and_resume_real_backend() -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    backend = BlockingBackend()
    app = create_app(
        service,
        butler=ButlerService(service, backend),
        allow_trusted_headers=True,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        pending = asyncio.create_task(
            client.post(
                "/v1/butler/messages",
                headers=HEADERS,
                json={"message": "打开 https://example.test 并等待"},
            )
        )
        await asyncio.wait_for(backend.started.wait(), timeout=2)
        assert backend.run_id is not None
        paused = await client.post(f"/v1/runs/{backend.run_id}/pause", headers=HEADERS)
        resumed = await client.post(f"/v1/runs/{backend.run_id}/resume", headers=HEADERS)
        completed = await asyncio.wait_for(pending, timeout=2)

    assert paused.json()["state"] == "paused"
    assert resumed.json()["state"] == "running"
    assert completed.json()["kind"] == "completed"
    assert backend.controls == ["pause", "resume"]
