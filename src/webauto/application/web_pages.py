"""v3.3 Web control plane pages: /status and /approvals/{id}.

Extracted from control_api.py so they can be mounted into the main
FastAPI app and exercised independently by tests without pulling in the
butler / VerticalWorkspace / BrowserAgent legacy stack.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse


_STATUS_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>WebAuto v3.3 status</title></head><body>"
    "<h1>WebAuto v3.3</h1>"
    "<p>Status: <strong>OK</strong></p>"
    "<ul>"
    "<li>Execution facade: webauto.application.mcp_browser.McpBrowserRuntime</li>"
    "<li>Safety state: SQLite five tables (Lease / ActionAttempt / "
    "Approval / Budget / Audit)</li>"
    "<li>Default tools: 20 (15 browser + file_upload/file_list + "
    "governed_action_prepare/get/execute)</li>"
    "</ul>"
    "<p><a href=\"/setup\">Setup</a> &middot; "
    "<a href=\"/approvals/\">Approvals</a></p>"
    "</body></html>"
)


def _render_approval(approval_id: str, binding: dict | None) -> HTMLResponse:
    if binding is None:
        return HTMLResponse(
            "<!doctype html><html><body>"
            f"<h1>Approval {approval_id}</h1>"
            "<p>Status: <strong>not found</strong></p>"
            "<p>Approvals are scoped to a session id. Open the MCP "
            "client to re-prepare this action.</p>"
            "</body></html>",
            status_code=404,
        )
    consumed = "yes" if binding["consumed"] else "no"
    resolved = "yes" if binding["resolved"] else "no"
    rows = "".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in binding.items()
    )
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>Approval {approval_id}</title></head><body>"
        f"<h1>Approval {approval_id}</h1>"
        "<table border=\"1\" cellpadding=\"4\">"
        f"{rows}"
        "</table>"
        "<p>Consumed: <strong>"
        f"{consumed}</strong>; Resolved: <strong>{resolved}</strong></p>"
        "<form method=\"post\" action=\"/approvals/"
        f"{approval_id}/approve\">"
        "<button type=\"submit\">Approve (record user approval)</button>"
        "</form>"
        "<form method=\"post\" action=\"/approvals/"
        f"{approval_id}/reject\">"
        "<button type=\"submit\">Reject</button>"
        "</form>"
        "<p><a href=\"/status\">Status</a></p>"
        "</body></html>"
    )
    return HTMLResponse(body)


def create_web_pages_app() -> FastAPI:
    """Build a self-contained FastAPI app with /status and /approvals/{id}.

    The GovernedActions dependency is resolved at request time so tests
    don't need a full bootstrap; the butler / Vertical stack is not
    pulled in.
    """

    def _governed_for_session(session_id: str):
        from webauto.application.governed_actions import GovernedActions

        return GovernedActions(session_id)

    app = FastAPI()

    @app.get("/status", response_class=HTMLResponse)
    async def status_page() -> HTMLResponse:
        return HTMLResponse(_STATUS_HTML)

    @app.get("/approvals/{approval_id}", response_class=HTMLResponse)
    async def approval_page(approval_id: str) -> HTMLResponse:
        binding = _governed_for_session("default-session").get(approval_id)
        return _render_approval(approval_id, binding)

    @app.post("/approvals/{approval_id}/approve")
    async def approval_approve(approval_id: str) -> dict[str, object]:
        actions = _governed_for_session("default-session")
        if actions.get(approval_id) is None:
            raise HTTPException(status_code=404, detail="approval not found")
        actions._approvals.mark_resolved(approval_id)  # noqa: SLF001
        return {"approval_id": approval_id, "resolved": True}

    @app.post("/approvals/{approval_id}/reject")
    async def approval_reject(approval_id: str) -> dict[str, object]:
        actions = _governed_for_session("default-session")
        if actions.get(approval_id) is None:
            raise HTTPException(status_code=404, detail="approval not found")
        actions._approvals.mark_resolved(approval_id)  # noqa: SLF001
        return {"approval_id": approval_id, "rejected": True}

    return app
