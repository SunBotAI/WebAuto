"""Durable, tenant-scoped conversation contracts for the personal butler."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ConversationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"


class ConversationRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationMessage(ConversationModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: ConversationRole
    content: str = Field(min_length=1, max_length=20_000)
    kind: str | None = Field(default=None, max_length=80)
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ButlerConversation(ConversationModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(min_length=1, max_length=160)
    status: ConversationStatus = ConversationStatus.ACTIVE
    messages: tuple[ConversationMessage, ...] = ()
    last_intent: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
