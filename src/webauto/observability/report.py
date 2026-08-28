"""Release baseline JSON report aggregated from MetricEvent streams.

Per plan §14.4: emit a JSON baseline report with low-cardinality
labels only — no error code, no identity, no full URL.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Iterable

from .events import EnvironmentKind, ErrorCategory, MetricEvent, RiskKind, StatusKind


def aggregate(events: Iterable[MetricEvent]) -> dict[str, object]:
    """Aggregate by low-cardinality labels (action × status × error × risk × environment)."""
    by_action_status: Counter = Counter()
    by_error: Counter = Counter()
    by_environment: Counter = Counter()
    by_risk: Counter = Counter()
    durations: list[int] = []
    total = 0
    succeeded = 0
    failed = 0
    blocked = 0
    waiting = 0
    uncertain = 0
    for e in events:
        total += 1
        by_action_status[(e.action.value, e.status.value)] += 1
        by_error[e.error_category.value] += 1
        by_environment[e.environment.value] += 1
        by_risk[e.risk.value] += 1
        durations.append(e.duration_ms)
        if e.status is StatusKind.SUCCEEDED:
            succeeded += 1
        elif e.status is StatusKind.FAILED:
            failed += 1
        elif e.status is StatusKind.BLOCKED:
            blocked += 1
        elif e.status is StatusKind.WAITING:
            waiting += 1
        elif e.status is StatusKind.UNCERTAIN:
            uncertain += 1
    durations.sort()
    p50 = durations[len(durations) // 2] if durations else 0
    p95 = durations[int(len(durations) * 0.95)] if durations else 0
    return {
        "total": total,
        "by_status": {
            "succeeded": succeeded,
            "failed": failed,
            "blocked": blocked,
            "waiting": waiting,
            "uncertain": uncertain,
        },
        "by_action_status": [
            {"action": k[0], "status": k[1], "count": v}
            for k, v in sorted(by_action_status.items())
        ],
        "by_error_category": sorted(by_error.items()),
        "by_environment": sorted(by_environment.items()),
        "by_risk": sorted(by_risk.items()),
        "latency_ms": {"p50": p50, "p95": p95, "samples": len(durations)},
    }


def render_report(events: Iterable[MetricEvent]) -> str:
    return json.dumps(aggregate(events), ensure_ascii=False, sort_keys=True, indent=2)
