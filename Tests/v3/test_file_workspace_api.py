"""Control API integration for the isolated user-file workspace."""

from __future__ import annotations

import base64

import pytest

from webauto.application import ApplicationService
from webauto.application.control_api import create_app
from webauto.application.settings import RuntimeConfigStore


@pytest.mark.asyncio
async def test_user_upload_must_be_explicitly_granted_to_owned_run(tmp_path) -> None:
    httpx = pytest.importorskip("httpx")
    service = ApplicationService()
    store = RuntimeConfigStore(tmp_path / "var")
    app = create_app(
        service,
        settings_store=store,
        allow_trusted_headers=True,
    )
    headers = {
        "x-user-id": "user-1",
        "x-tenant-id": "tenant-1",
        "x-roles": "operator",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        goal = await client.post(
            "/v1/goals",
            headers=headers,
            json={"objective": "prepare a draft", "success_criteria": ["draft ready"]},
        )
        run = await client.post(
            "/v1/runs",
            headers=headers,
            json={"goal_id": goal.json()["id"], "plan_id": "plan-file"},
        )
        uploaded = await client.post(
            "/v1/files",
            headers=headers,
            json={
                "filename": "product.png",
                "media_type": "image/png",
                "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nproduct").decode(),
            },
        )
        assert uploaded.status_code == 201
        file_id = uploaded.json()["id"]
        assert (await client.get("/v1/files", headers=headers)).json()[0]["id"] == file_id

        grant = await client.post(
            f"/v1/runs/{run.json()['id']}/files/{file_id}/authorize",
            headers=headers,
        )
        assert grant.status_code == 200
        assert grant.json()["file_id"] == file_id

        invalid = await client.post(
            "/v1/files",
            headers=headers,
            json={
                "filename": "payload.exe",
                "media_type": "application/octet-stream",
                "content_base64": base64.b64encode(b"MZ").decode(),
            },
        )
        assert invalid.status_code == 422
