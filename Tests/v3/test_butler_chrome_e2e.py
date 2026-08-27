"""Authorized local-only Chrome E2E for conversation-to-browser execution."""

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from webauto.application import Actor, ApplicationService, Role
from webauto.application.butler_service import ButlerService
from webauto.application.local_execution import LocalBrowserExecutionBackend
from webauto.application.settings import RuntimeConfigStore


class _Page(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        payload = "<html><head><title>Butler Fixture</title></head><body><h1>已验证商品页面</h1><p>价格 2999</p></body></html>".encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_conversation_executes_and_verifies_real_chrome(tmp_path: Path) -> None:
    executable = os.environ.get("WEBAUTO_CHROME_EXECUTABLE")
    if not executable or not os.path.exists(executable):
        pytest.skip("WEBAUTO_CHROME_EXECUTABLE is not available on this platform")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(_execute(tmp_path, server.server_port, executable))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _execute(tmp_path: Path, port: int, executable: str) -> None:
    settings = RuntimeConfigStore(tmp_path / "var")
    settings.update(
        {
            "browser": {"mode": "managed", "executable": executable, "headless": True},
            "storage": {
                "profiles_dir": str(tmp_path / "profiles"),
                "artifacts_dir": str(tmp_path / "artifacts"),
            },
        },
        {},
    )
    application = ApplicationService()
    butler = ButlerService(application, LocalBrowserExecutionBackend(settings))
    actor = Actor("owner", "personal", {Role.OPERATOR, Role.APPROVER})
    reply = await butler.handle(
        actor,
        f"打开 http://127.0.0.1:{port}/product 看一下，只看不要买",
    )
    assert reply.kind == "completed", reply
    outputs = reply.payload["result"]["outputs"]
    assert "已验证商品页面" in outputs["step-2"]["text"]
    assert any((tmp_path / "artifacts").glob("*.png"))
