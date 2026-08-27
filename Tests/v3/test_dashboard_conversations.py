"""Task and conversation orchestration belongs to the external MCP agent."""

from webauto.application.dashboard import DASHBOARD_HTML


def test_dashboard_has_no_internal_task_or_conversation_controls() -> None:
    for element_id in (
        "conversation-status",
        "new-conversation",
        "refresh-history",
        "conversation-list",
        "run-list",
        "history-output",
        "objective",
        "create-goal",
    ):
        assert f'id="{element_id}"' not in DASHBOARD_HTML
    assert "/conversations" not in DASHBOARD_HTML
    assert "/runs?limit=100" not in DASHBOARD_HTML
    assert 'id="load-mcp"' in DASHBOARD_HTML
    assert "/settings/mcp-client-config" in DASHBOARD_HTML