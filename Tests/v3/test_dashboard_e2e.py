"""Real Chrome smoke for the zero-configuration MCP onboarding surface."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from webauto.application.dashboard import DASHBOARD_HTML


class _DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _json(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in {"/", "/setup"}:
            payload = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/v1/health":
            self._json({"status": "ok", "setup_complete": True})
        elif self.path == "/v1/settings":
            self._json(
                {
                    "environment": "development",
                    "runtime_dir": "var",
                    "browser": {
                        "mode": "managed",
                        "executable": "/usr/bin/google-chrome",
                        "cdp_endpoint": "http://127.0.0.1:9222",
                        "headless": False,
                    },
                    "model": {"provider": "openai-compatible", "base_url": "", "model": ""},
                    "browser_agent": {
                        "backend": "local",
                        "enabled": False,
                        "allow_unrestricted_domains": False,
                        "max_steps": 50,
                        "max_duration_seconds": 1200,
                    },
                    "storage": {"profiles_dir": "data/profiles", "artifacts_dir": "var/artifacts"},
                    "policy": {"purchase_approval_amount": 0, "publish_requires_approval": True},
                    "sites": {"taobao": True, "jd": True, "xianyu": True},
                    "secrets": {"database_url": False, "redis_url": False, "model_api_key": False},
                    "setup_complete": True,
                }
            )
        elif self.path == "/v1/settings/mcp-client-config":
            self._json(
                {
                    "mode": "mcp-first",
                    "transport": "stdio",
                    "server": {"command": "wsl.exe", "args": ["-e", "webauto-mcp"]},
                    "generic_json": '{"mcpServers":{"webauto":{"command":"wsl.exe"}}}',
                    "codex_toml": '[mcp_servers.webauto]\ncommand = "wsl.exe"',
                    "tool_count": 50,
                    "authentication": {
                        "credential_visible_to_agent": False,
                        "credential_injected_by_server": True,
                    },
                    "requirements": {
                        "internal_model_required": False,
                        "postgres_required_for_local_personal_mode": False,
                        "redis_required_for_local_stdio": False,
                    },
                }
            )
        else:
            self._json({"detail": "not found"}, 404)


def test_dashboard_auto_loads_agent_mcp_config_in_real_chrome() -> None:
    executable = os.environ.get("WEBAUTO_CHROME_EXECUTABLE")
    if not executable or not os.path.exists(executable):
        pytest.skip("WEBAUTO_CHROME_EXECUTABLE is not available on this platform")
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=executable, headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/setup")
            assert page.locator("#create-goal").count() == 0
            assert page.locator("#setup-token").count() == 0
            page.wait_for_function(
                "document.querySelector('#mcp-tool-count').textContent.includes('50')"
            )
            assert "wsl.exe" in page.locator("#mcp-json").text_content()
            assert "mcp-first" in page.locator("#mcp-output").text_content()
            assert page.locator("#advanced-settings").get_attribute("open") is None
            assert "WebAuto 不保存账号密码" in page.locator("body").text_content()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)