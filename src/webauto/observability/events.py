"""Structured MetricEvent for the v3.3 release baseline.

Per plan §14.4: labels must stay low-cardinality (action kind,
status, error category, risk, environment type). The full error code
and identity-shaped fields live in the audit_events SQLite table;
they are NOT used as Prometheus / metric labels.
"""

from __future__ import annotations

import enum
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


class ActionKind(str, enum.Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    WAIT = "wait"
    SNAPSHOT = "snapshot"
    SCREENSHOT = "screenshot"
    OPEN = "open"
    CLOSE = "close"
    GOVERNED = "governed"
    UNKNOWN = "unknown"


class StatusKind(str, enum.Enum):
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    WAITING = "waiting"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class ErrorCategory(str, enum.Enum):
    NONE = "none"
    REQUEST = "request"
    PAGE_STATE = "page_state"
    AUTHORIZATION = "authorization"
    GOVERNANCE = "governance"
    ENVIRONMENT = "environment"
    OUTCOME = "outcome"
    INTERNAL = "internal"


class RiskKind(str, enum.Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class EnvironmentKind(str, enum.Enum):
    MANAGED = "managed"
    CDP = "cdp"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MetricEvent:
    event_id: str = field(default_factory=lambda: "me-" + uuid.uuid4().hex)
    occurred_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    action: ActionKind = ActionKind.UNKNOWN
    status: StatusKind = StatusKind.SUCCEEDED
    error_category: ErrorCategory = ErrorCategory.NONE
    risk: RiskKind = RiskKind.L0
    environment: EnvironmentKind = EnvironmentKind.UNKNOWN
    duration_ms: int = 0

    def to_json(self) -> str:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["status"] = self.status.value
        payload["error_category"] = self.error_category.value
        payload["risk"] = self.risk.value
        payload["environment"] = self.environment.value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def validate_label_cardinality(event: MetricEvent) -> list[str]:
    """Return an empty list if all labels stay low-cardinality; else offending label names."""
    violations: list[str] = []
    # The five labels enumerated in plan §14.4 each have a small fixed enum.
    allowed = {
        "action": {a.value for a in ActionKind},
        "status": {s.value for s in StatusKind},
        "error_category": {c.value for c in ErrorCategory},
        "risk": {r.value for r in RiskKind},
        "environment": {e.value for e in EnvironmentKind},
    }
    labels = {
        "action": event.action.value if hasattr(event.action, "value") else event.action,
        "status": event.status.value if hasattr(event.status, "value") else event.status,
        "error_category": (event.error_category.value
                          if hasattr(event.error_category, "value")
                          else event.error_category),
        "risk": event.risk.value if hasattr(event.risk, "value") else event.risk,
        "environment": (event.environment.value
                        if hasattr(event.environment, "value")
                        else event.environment),
    }
    for name, value in labels.items():
        if value not in allowed[name]:
            violations.append(f"{name}={value}")
    return violations
