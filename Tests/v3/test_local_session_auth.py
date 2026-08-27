"""Local browser session and CSRF boundary tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from webauto.application import ApplicationService
from webauto.application.auth import LocalSessionError, LocalSessionManager
from webauto.application.control_api import create_app
from webauto.application.settings import RuntimeConfigStore


def test_local_session_is_signed_and_expires(tmp_path) -> None:
    current = [datetime(2026, 8, 25, tzinfo=timezone.utc)]
    sessions = LocalSessionManager(
        tmp_path / "session.key",
        ttl=timedelta(minutes=5),
        clock=lambda: current[0],
    )
    issued = sessions.issue()

    actor = sessions.authenticate(issued.token)
    assert actor.user_id == "local-user"
    assert {role.value for role in actor.roles} == {"admin"}
    sessions.verify_csrf(issued.token, issued.csrf_token)

    payload, signature = issued.token.split(".")
    with pytest.raises(LocalSessionError, match="signature"):
        sessions.authenticate(payload + "." + signature[:-1] + "x")

    current[0] += timedelta(minutes=6)
    with pytest.raises(LocalSessionError, match="expired"):
        sessions.authenticate(issued.token)


@pytest.mark.asyncio
async def test_control_api_ignores_forged_roles_and_requires_csrf(tmp_path) -> None:
    httpx = pytest.importorskip("httpx")
    store = RuntimeConfigStore(tmp_path / "var")
    app = create_app(ApplicationService(), settings_store=store)
    transport = httpx.ASGITransport(app=app)
    forged = {
        "x-user-id": "attacker",
        "x-tenant-id": "other",
        "x-roles": "admin",
    }
    payload = {"objective": "查看授权页面", "success_criteria": ["结果已验证"]}

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post("/v1/goals", headers=forged, json=payload)
        assert blocked.status_code == 403

        bad_bootstrap = await client.post(
            "/v1/session/bootstrap",
            headers={"x-webauto-setup-token": "wrong"},
        )
        assert bad_bootstrap.status_code == 401

        bootstrap = await client.post(
            "/v1/session/bootstrap",
            headers={"x-webauto-setup-token": store.authorizer.token()},
        )
        assert bootstrap.status_code == 200
        csrf = bootstrap.json()["csrf_token"]

        missing_csrf = await client.post("/v1/goals", json=payload)
        assert missing_csrf.status_code == 403

        created = await client.post(
            "/v1/goals",
            headers={**forged, "x-webauto-csrf-token": csrf},
            json=payload,
        )
        assert created.status_code == 201
        session = await client.get("/v1/session")
        assert session.json()["user_id"] == "local-user"
        assert session.json()["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_control_api_rejects_non_local_host_header(tmp_path) -> None:
    httpx = pytest.importorskip("httpx")
    store = RuntimeConfigStore(tmp_path / "var")
    app = create_app(ApplicationService(), settings_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/health", headers={"host": "evil.example"})
    assert response.status_code == 400
