"""Local browser discovery and protected API tests."""

from pathlib import Path

import pytest

from webauto.application import ApplicationService
from webauto.application.control_api import create_app
from webauto.application.settings import RuntimeConfigStore
from webauto.runtime.browser.discovery import discover_browsers


def test_discovery_deduplicates_configured_executable(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "chrome"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("WEBAUTO_CHROME_EXECUTABLE", str(executable))
    result = discover_browsers()
    assert result["browsers"][0]["executable"] == str(executable.resolve())
    assert result["browsers"][0]["kind"] == "configured"


@pytest.mark.asyncio
async def test_discovery_api_requires_setup_token(tmp_path: Path) -> None:
    httpx = pytest.importorskip("httpx")
    store = RuntimeConfigStore(tmp_path / "var")
    token = store.authorizer.token()
    app = create_app(ApplicationService(), settings_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.get("/v1/settings/detect-browser")
        allowed = await client.get(
            "/v1/settings/detect-browser", headers={"x-webauto-setup-token": token}
        )
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert set(allowed.json()) == {"browsers", "cdp_endpoints"}
