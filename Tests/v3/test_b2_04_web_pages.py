"""B2-04 /setup, /status, /approvals/{id} three-page Web E2E."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_session(tmp_path, monkeypatch: pytest.MonkeyPatch):
    import shutil
    gov_dir = Path(tempfile.gettempdir()) / "webauto-governed"
    if gov_dir.exists():
        shutil.rmtree(gov_dir, ignore_errors=True)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    yield


@pytest.fixture
def make_client(isolated_session):
    from webauto.application.web_pages import create_web_pages_app

    def _factory() -> TestClient:
        return TestClient(create_web_pages_app())
    return _factory


def test_status_renders_v33_summary(make_client) -> None:
    client = make_client()
    response = client.get("/status")
    assert response.status_code == 200
    body = response.text
    assert "WebAuto v3.3" in body
    assert "McpBrowserRuntime" in body
    assert "22" in body


def test_approval_page_lookup(make_client) -> None:
    client = make_client()
    from webauto.application.governed_actions import GovernedActions

    actions = GovernedActions("non-default-web-session")
    prep = actions.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-e2e-page",
        page_revision="rev-e2e-page",
        target={"url": "https://example.test/post", "fields": ["title", "price"]},
        content_digest="sha256:e2e-page",
    )
    response = client.get(f"/approvals/{prep.approval_id}")
    assert response.status_code == 200
    body = response.text
    assert prep.approval_id in body
    assert prep.action_hash in body
    assert "rev-e2e-page" in body


def test_approval_page_unknown_id_404(make_client) -> None:
    client = make_client()
    response = client.get("/approvals/apr-does-not-exist")
    assert response.status_code == 404
    assert "not found" in response.text


def test_approval_approve_marks_resolved(make_client) -> None:
    client = make_client()
    from webauto.application.governed_actions import GovernedActions

    actions = GovernedActions("default-session")
    prep = actions.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-e2e-approve",
        page_revision="rev-e2e-approve",
        target={"url": "https://example.test/post"},
        content_digest="sha256:e2e-approve",
    )
    response = client.post(
        f"/approvals/{prep.approval_id}/approve", follow_redirects=False
    )
    assert response.status_code == 200
    assert response.json() == {"approval_id": prep.approval_id, "resolved": True}
    binding = actions.get(prep.approval_id)
    assert binding is not None
    assert binding["resolved"] is True


def test_approval_reject_marks_resolved(make_client) -> None:
    client = make_client()
    from webauto.application.governed_actions import GovernedActions

    actions = GovernedActions("default-session")
    prep = actions.prepare(
        action_type="builtin_test_listing_publish",
        client_request_id="req-e2e-reject",
        page_revision="rev-e2e-reject",
        target={"url": "https://example.test/post"},
        content_digest="sha256:e2e-reject",
    )
    response = client.post(
        f"/approvals/{prep.approval_id}/reject", follow_redirects=False
    )
    assert response.status_code == 200
    assert response.json() == {"approval_id": prep.approval_id, "rejected": True}
    binding = actions.get(prep.approval_id)
    assert binding is not None
    assert binding["resolved"] is True
    assert binding["consumed"] is True


def test_agent_tools_have_no_self_approval() -> None:
    """Plan §17.3 B1-02/B2-04: Agent cannot approve its own actions."""
    from webauto.application.mcp import list_agent_tools

    names = {t["name"] for t in list_agent_tools()}
    assert "approval_approve" not in names
    assert "approval_reject" not in names
    assert "approval_revoke" not in names
    assert "governed_action_get" in names
