"""Scenario-neutral contracts for dynamic browser-agent execution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import Placement, RiskLevel


class AgentTaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"


class AgentTaskStatus(str, Enum):
    """A dynamic agent may complete a trace before WebAuto verifies the goal."""

    COMPLETED = "completed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    WAITING_HUMAN = "waiting_human"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


class AgentTaskBudget(AgentTaskModel):
    max_steps: int = Field(default=50, ge=1, le=500)
    max_duration_seconds: float = Field(default=1200, gt=0, le=14_400)
    max_model_cost: float | None = Field(default=None, ge=0)
    max_recovery_attempts: int = Field(default=3, ge=0, le=20)
    max_external_writes: int = Field(default=0, ge=0, le=100)


class AgentTaskRequest(AgentTaskModel):
    run_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    placement: Placement
    allowed_domains: tuple[str, ...] = Field(min_length=1)
    allow_unrestricted_domains: bool = False
    prohibited_actions: tuple[str, ...] = (
        "payment",
        "refund",
        "delete",
        "publish",
        "place_order",
    )
    available_files: tuple[Path, ...] = ()
    output_schema: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True
    max_risk: RiskLevel = RiskLevel.L1
    budget: AgentTaskBudget = Field(default_factory=AgentTaskBudget)

    @model_validator(mode="after")
    def validate_security_scope(self) -> AgentTaskRequest:
        domains = tuple(item.strip() for item in self.allowed_domains)
        if not all(domains):
            raise ValueError("allowed_domains cannot contain blank entries")
        if "*" in domains and not self.allow_unrestricted_domains:
            raise ValueError("'*' requires allow_unrestricted_domains=true")
        for scope in domains:
            if scope == "*":
                continue
            if "://" in scope:
                parsed = urlparse(scope)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or "*" in scope
                ):
                    raise ValueError("URL domain scopes must be exact HTTP(S) URLs")
            elif "*" in scope:
                if not scope.startswith("*.") or scope.count("*") != 1:
                    raise ValueError("wildcard domain scopes must use the '*.example.com' form")
            elif any(value in scope for value in ("/", "@", "?", "#", " ")):
                raise ValueError("domain scopes must be hostnames or exact HTTP(S) URLs")
        if self.read_only and self.budget.max_external_writes:
            raise ValueError("read-only tasks cannot allow external writes")
        if not self.read_only and self.max_risk.rank < RiskLevel.L2.rank:
            raise ValueError("write-capable tasks require max_risk L2 or higher")
        object.__setattr__(self, "allowed_domains", domains)
        return self


class AgentTaskResult(AgentTaskModel):
    status: AgentTaskStatus
    verified: bool = False
    output: dict[str, Any] = Field(default_factory=dict)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    visited_urls: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    steps_used: int = Field(default=0, ge=0)
    model_cost: float = Field(default=0, ge=0)
    requires_human: bool = False
    error: str | None = None

    @model_validator(mode="after")
    def verified_success_only(self) -> AgentTaskResult:
        if self.status == AgentTaskStatus.SUCCEEDED and not self.verified:
            raise ValueError("succeeded agent task must be independently verified")
        if self.status == AgentTaskStatus.WAITING_HUMAN and not self.requires_human:
            raise ValueError("waiting_human requires requires_human=true")
        return self

    @property
    def requires_verification(self) -> bool:
        return self.status == AgentTaskStatus.COMPLETED and not self.verified


class AgentTaskEventKind(str, Enum):
    STARTED = "started"
    OBSERVED = "observed"
    PLANNED = "planned"
    TOOL_REQUESTED = "tool_requested"
    TOOL_COMPLETED = "tool_completed"
    PAUSED = "paused"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentTaskEvent(AgentTaskModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    kind: AgentTaskEventKind
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
