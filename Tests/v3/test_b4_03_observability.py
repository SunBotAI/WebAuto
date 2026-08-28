"""B4-03 MetricEvent low-cardinality + release baseline report."""

from __future__ import annotations

import json

from webauto.observability.events import (
    ActionKind,
    EnvironmentKind,
    ErrorCategory,
    MetricEvent,
    RiskKind,
    StatusKind,
    validate_label_cardinality,
)
from webauto.observability.report import aggregate, render_report


def test_metric_event_low_cardinality_labels() -> None:
    e = MetricEvent(
        action=ActionKind.NAVIGATE,
        status=StatusKind.SUCCEEDED,
        error_category=ErrorCategory.NONE,
        risk=RiskKind.L0,
        environment=EnvironmentKind.MANAGED,
    )
    assert validate_label_cardinality(e) == []


def test_metric_event_rejects_free_form_label() -> None:
    # Replace an enum value via __dict__ bypass; validation must catch it.
    e = MetricEvent(
        action=ActionKind.OPEN,
        status=StatusKind.SUCCEEDED,
        error_category=ErrorCategory.NONE,
        risk=RiskKind.L0,
        environment=EnvironmentKind.MANAGED,
    )
    object.__setattr__(e, "action", "FREE_FORM_VALUE")  # type: ignore[arg-type]
    violations = validate_label_cardinality(e)
    assert "action=FREE_FORM_VALUE" in violations


def test_metric_event_to_json_round_trip() -> None:
    e = MetricEvent(
        action=ActionKind.GOVERNED,
        status=StatusKind.WAITING,
        error_category=ErrorCategory.AUTHORIZATION,
        risk=RiskKind.L2,
        environment=EnvironmentKind.MANAGED,
        duration_ms=42,
    )
    payload = json.loads(e.to_json())
    assert payload["action"] == "governed"
    assert payload["status"] == "waiting"
    assert payload["error_category"] == "authorization"
    assert payload["duration_ms"] == 42


def test_aggregate_counts_by_status() -> None:
    events = [
        MetricEvent(action=ActionKind.NAVIGATE, status=StatusKind.SUCCEEDED,
                    error_category=ErrorCategory.NONE, risk=RiskKind.L0,
                    environment=EnvironmentKind.MANAGED, duration_ms=10),
        MetricEvent(action=ActionKind.CLICK, status=StatusKind.SUCCEEDED,
                    error_category=ErrorCategory.NONE, risk=RiskKind.L0,
                    environment=EnvironmentKind.MANAGED, duration_ms=20),
        MetricEvent(action=ActionKind.CLICK, status=StatusKind.WAITING,
                    error_category=ErrorCategory.AUTHORIZATION, risk=RiskKind.L2,
                    environment=EnvironmentKind.MANAGED, duration_ms=30),
        MetricEvent(action=ActionKind.NAVIGATE, status=StatusKind.FAILED,
                    error_category=ErrorCategory.NETWORK_BLOCKED if hasattr(
                        ErrorCategory, "NETWORK_BLOCKED"
                    ) else ErrorCategory.GOVERNANCE, risk=RiskKind.L2,
                    environment=EnvironmentKind.MANAGED, duration_ms=200),
    ]
    agg = aggregate(events)
    assert agg["total"] == 4
    assert agg["by_status"]["succeeded"] == 2
    assert agg["by_status"]["waiting"] == 1
    assert agg["by_status"]["failed"] == 1
    assert agg["latency_ms"]["samples"] == 4
    assert agg["latency_ms"]["p50"] == 30  # sorted: [10, 20, 30, 200]; index len//2 = 2
    assert agg["latency_ms"]["p95"] == 200


def test_render_report_is_valid_json() -> None:
    events = [
        MetricEvent(action=ActionKind.SNAPSHOT, status=StatusKind.SUCCEEDED,
                    error_category=ErrorCategory.NONE, risk=RiskKind.L0,
                    environment=EnvironmentKind.MANAGED, duration_ms=15),
    ]
    report = render_report(events)
    parsed = json.loads(report)
    assert "total" in parsed
    assert parsed["total"] == 1
    assert "by_status" in parsed
    # No identity / no error code fields must leak into the report.
    serialized = report.lower()
    assert "session_id" not in serialized
    assert "approval_id" not in serialized
    assert "fencing_token" not in serialized
