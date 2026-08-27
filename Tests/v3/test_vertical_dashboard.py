"""Vertical workflows remain MCP tools and are not duplicated in Web UI."""

from webauto.application.dashboard import DASHBOARD_HTML


def test_dashboard_does_not_duplicate_vertical_task_workspaces() -> None:
    for element_id in (
        "vertical-workspaces",
        "vertical-kind",
        "create-vertical-workspace",
        "governed-actions",
        "prepare-governed-action",
        "execute-governed-action",
    ):
        assert f'id="{element_id}"' not in DASHBOARD_HTML
    assert "/vertical/workspaces/" not in DASHBOARD_HTML
    assert "/governed-actions/" not in DASHBOARD_HTML
    assert "一次性写审批" in DASHBOARD_HTML
    assert "支付永远不自动化" in DASHBOARD_HTML