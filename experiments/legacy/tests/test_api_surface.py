"""M6 control surface and application-layer dependency checks."""

from pathlib import Path

from webauto.application import ApplicationService
from webauto.application.control_api import create_app


def test_control_api_exposes_required_product_resources() -> None:
    paths = {route.path for route in create_app(ApplicationService()).routes}
    assert {
        "/v1/goals",
        "/v1/runs",
        "/v1/runs/{run_id}",
        "/v1/runs/{run_id}/detail",
        "/v1/runs/{run_id}/plans",
        "/v1/runs/{run_id}/approvals",
        "/v1/approvals",
        "/v1/approvals/{approval_id}/approve",
        "/v1/approvals/{approval_id}/reject",
        "/v1/approvals/{approval_id}/revoke",
        "/v1/resources/{category}",
        "/v1/agents",
        "/v1/profiles",
        "/v1/artifacts",
        "/v1/events",
    } <= paths


def test_application_layer_does_not_import_legacy_or_infrastructure_modules() -> None:
    root = Path(__file__).parents[2] / "src/webauto/application"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in (
        "from Core",
        "import Core",
        "from Tools",
        "import Tools",
        "playwright",
        "psycopg",
        "redis.asyncio",
    ):
        assert forbidden not in source
