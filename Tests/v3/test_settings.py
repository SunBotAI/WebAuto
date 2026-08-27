"""Configuration-center persistence, secrecy and API authorization tests."""

from pathlib import Path

import pytest

from webauto.application import ApplicationService
from webauto.application.control_api import create_app
from webauto.application.settings import RuntimeConfigStore
from webauto.runtime.browser import (
    BrowserAttachProvider,
    DesktopManagedProvider,
    configured_browser,
)


def test_settings_store_encrypts_secrets_and_never_returns_values(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    result = store.update(
        {
            "environment": "development",
            "browser": {"mode": "managed", "executable": "/browser"},
            "model": {"model": "model-1"},
        },
        {
            "database_url": "postgresql://private-password@localhost/webauto",
            "redis_url": "redis://localhost:6379/0",
            "model_api_key": "private-api-key",
        },
    )

    assert result["secrets"] == {
        "database_url": True,
        "redis_url": True,
        "model_api_key": True,
    }
    encrypted = store.secrets.path.read_bytes()
    assert b"private-password" not in encrypted
    assert b"private-api-key" not in encrypted
    assert "database_url" not in store.path.read_text(encoding="utf-8")
    assert store.secret("model_api_key") == "private-api-key"


def test_blank_secret_update_preserves_existing_value(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update({}, {"model_api_key": "keep-me"})
    store.update({"browser": {"headless": True}}, {})
    assert store.secret("model_api_key") == "keep-me"


@pytest.mark.asyncio
async def test_settings_api_requires_setup_token_and_masks_secrets(tmp_path: Path) -> None:
    httpx = pytest.importorskip("httpx")
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.authorizer.token()
    app = create_app(ApplicationService(), settings_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.get("/v1/settings")
        assert denied.status_code == 401
        saved = await client.put(
            "/v1/settings",
            headers={"x-webauto-setup-token": token},
            json={
                "settings": {
                    "environment": "development",
                    "browser": {"mode": "cdp"},
                    "policy": {"purchase_approval_amount": 100},
                },
                "secrets": {"redis_url": "redis://localhost:6379/0"},
            },
        )
        assert saved.status_code == 200
        assert saved.json()["restart_required"] is True
        loaded = await client.get("/v1/settings", headers={"x-webauto-setup-token": token})
        body = loaded.json()
        assert body["browser"]["mode"] == "cdp"
        assert body["secrets"]["redis_url"] is True
        assert "redis://" not in loaded.text


@pytest.mark.asyncio
async def test_health_exposes_only_setup_status(tmp_path: Path) -> None:
    httpx = pytest.importorskip("httpx")
    store = RuntimeConfigStore(tmp_path / "var")
    app = create_app(ApplicationService(), settings_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        initial = await client.get("/v1/health")
        assert initial.json()["setup_complete"] is False
        store.update({}, {})
        configured = await client.get("/v1/health")
        assert configured.json()["setup_complete"] is True


def test_saved_browser_configuration_builds_runtime_provider(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "var")
    store.update(
        {
            "browser": {"mode": "managed", "executable": "/opt/chrome", "headless": True},
            "storage": {"profiles_dir": str(tmp_path / "profiles")},
        },
        {},
    )
    managed = configured_browser(store)
    assert managed.mode == "managed"
    assert isinstance(managed.provider, DesktopManagedProvider)
    assert managed.provider._launch_options["executable_path"] == "/opt/chrome"
    assert managed.provider._headless is True

    store.update({"browser": {"mode": "cdp", "cdp_endpoint": "http://127.0.0.1:9222"}}, {})
    attached = configured_browser(store)
    assert isinstance(attached.provider, BrowserAttachProvider)
    assert attached.endpoint == "http://127.0.0.1:9222"
