"""Shared application-service container and transport DTO helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from .service import Actor, Role


def actor_from_payload(payload: dict[str, Any]) -> Actor:
    """Build a tenant-scoped actor from an explicit transport context."""
    user_id = str(payload.pop("user_id", "")).strip()
    tenant_id = str(payload.pop("tenant_id", "")).strip()
    raw_roles = payload.pop("roles", [])
    if not user_id or not tenant_id:
        raise ValueError("user_id and tenant_id are required")
    if isinstance(raw_roles, str):
        raw_roles = [item.strip() for item in raw_roles.split(",") if item.strip()]
    roles = {Role(str(item)) for item in raw_roles}
    if not roles:
        raise ValueError("at least one role is required")
    return Actor(user_id=user_id, tenant_id=tenant_id, roles=roles)


def jsonable(value: Any) -> Any:
    """Convert domain return values to transport-safe JSON data."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value
