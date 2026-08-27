"""Real Chrome smoke for optional advanced settings behind local session auth."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from webauto.application.dashboard import DASHBOARD_HTML


class _Handler(BaseHTTPRequestHandler):
    saved_payload = None
    csrf_header = None

    def log_message(self, format, *args):
        return

    def send_json(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/setup":
            payload = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/v1/health":
            self.send_json({"status": "ok", "setup_complete": True})
        elif self.path == "/v1/settings":
            self.send_json(
                {
                    "environment": "development",
                    "runtime_dir": "var",
                    "browser": {
                        "mode": "managed",
                        "executable": "C:/chrome.exe",
                        "cdp_endpoint": "http://127.0.0.1:9222",
                        "headless": False,
                    },
                    "model": {"provider": "test", "base_url": "", "model": "model-1"},
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
                    "secrets": {"database_url": False, "redis_url": True, "model_api_key": False},
                    "setup_complete": True,
                }
            )
        elif self.path == "/v1/settings/mcp-client-config":
            self.send_json(
                {
                    "mode": "mcp-first",
                    "transport": "stdio",
                    "server": {"command": "python", "args": ["-m", "webauto.adapters.mcp_server"]},
                    "generic_json": "{}",
                    "codex_toml": "[mcp_servers.webauto]",
                    "tool_count": 50,
                    "authentication": {},
                    "requirements": {"internal_model_required": False},
                }
            )
        else:
            self.send_json({"detail": "not found"}, 404)

    def do_PUT(self):
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        if self.path == "/v1/settings" and self.headers.get("x-webauto-csrf-token"):
            self.__class__.csrf_header = self.headers["x-webauto-csrf-token"]
            self.__class__.saved_payload = json.loads(body)
            self.send_json({"setup_complete": True, "restart_required": True})
        else:
            self.send_json({}, 403)


def test_advanced_configuration_loads_and_saves_in_real_chrome() -> None:
    executable = os.environ.get("WEBAUTO_CHROME_EXECUTABLE")
    if not executable or not os.path.exists(executable):
        pytest.skip("WEBAUTO_CHROME_EXECUTABLE is not available on this platform")
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _Handler.saved_payload = None
    _Handler.csrf_header = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=executable, headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/setup")
            page.wait_for_function("document.querySelector('#cfg-model-name').value === 'model-1'")
            assert page.locator("#setup-token").count() == 0
            page.locator("#advanced-settings summary").click()
            page.locator("#cfg-agent-enabled").check()
            page.locator("#cfg-agent-backend").select_option("browser_use")
            page.locator("#cfg-agent-max-steps").fill("25")
            page.locator("#cfg-agent-max-duration").fill("600")
            page.locator("#cfg-agent-unrestricted-domains").check()
            page.locator("#cfg-approval-amount").fill("88")
            page.locator("#save-settings").click()
            page.wait_for_function("document.querySelector('#settings-output').textContent.includes('restart_required')")
            assert page.locator("#secret-redis-url").input_value() == ""
            assert _Handler.csrf_header
            assert _Handler.saved_payload["settings"]["browser_agent"] == {
                "enabled": True,
                "backend": "browser_use",
                "max_steps": 25,
                "max_duration_seconds": 600,
                "allow_unrestricted_domains": True,
            }
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)