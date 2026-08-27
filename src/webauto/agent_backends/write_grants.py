"""Cryptographically bound, process-local grants for one approved browser write."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from webauto.domain import AgentTaskRequest


class BrowserWriteGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    object_digest: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    file_digests: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime
    signature: str = Field(min_length=1)


class BrowserWriteGrantAuthority:
    """Issue and consume grants that cannot be forged through Agent context."""

    context_key = "approved_external_write"

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("browser write grant secret must be at least 32 bytes")
        self._issued: dict[str, BrowserWriteGrant] = {}
        self._consumed: set[str] = set()

    def issue(
        self,
        *,
        run_id: str,
        operation: str,
        object_digest: str,
        source_url: str,
        files: tuple[Path, ...] = (),
        ttl: timedelta = timedelta(minutes=2),
    ) -> BrowserWriteGrant:
        if ttl.total_seconds() <= 0 or ttl > timedelta(minutes=5):
            raise ValueError("browser write grant ttl must be between 0 and 5 minutes")
        file_digests = {
            str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in files
        }
        unsigned = {
            "id": str(uuid4()),
            "run_id": run_id,
            "operation": operation,
            "object_digest": object_digest,
            "source_url": source_url,
            "file_digests": file_digests,
            "expires_at": (datetime.now(timezone.utc) + ttl).isoformat(),
        }
        grant = BrowserWriteGrant(
            **unsigned,
            signature=self._sign(unsigned),
        )
        self._issued[grant.id] = grant
        return grant

    def validate_request(self, request: AgentTaskRequest) -> BrowserWriteGrant:
        raw = request.context.get(self.context_key)
        try:
            grant = BrowserWriteGrant.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise PermissionError("write-capable task has no valid internal grant") from exc
        issued = self._issued.get(grant.id)
        if issued is None or not hmac.compare_digest(issued.signature, grant.signature):
            raise PermissionError("browser write grant was not issued by this process")
        if not hmac.compare_digest(self._sign(self._unsigned(grant)), grant.signature):
            raise PermissionError("browser write grant signature is invalid")
        if grant.id in self._consumed:
            raise PermissionError("browser write grant was already consumed")
        if datetime.now(timezone.utc) >= grant.expires_at:
            raise PermissionError("browser write grant expired")
        approved_object = request.context.get("approved_object")
        if not isinstance(approved_object, dict):
            raise PermissionError("browser write grant has no approved object")
        object_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    approved_object,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        if not hmac.compare_digest(grant.object_digest, object_digest):
            raise PermissionError("browser write approved object digest changed")
        if approved_object.get("source_url") != grant.source_url:
            raise PermissionError("browser write approved source URL changed")
        if grant.run_id != request.run_id:
            raise PermissionError("browser write grant run binding does not match")
        if request.read_only or request.budget.max_external_writes != 1:
            raise PermissionError("browser write grant requires exactly one external write")
        actual_files = {str(path.resolve()) for path in request.available_files}
        if actual_files != set(grant.file_digests):
            raise PermissionError("browser write grant file scope does not match")
        for path in request.available_files:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if not hmac.compare_digest(grant.file_digests[str(path.resolve())], digest):
                raise PermissionError("browser write grant file checksum changed")
        return grant

    def consume(self, request: AgentTaskRequest, *, observed_operation: str) -> BrowserWriteGrant:
        grant = self.validate_request(request)
        expected = "xianyu_send_message" if grant.operation == "xianyu_reply" else grant.operation
        if not hmac.compare_digest(expected, observed_operation):
            raise PermissionError("browser write operation does not match its grant")
        self._consumed.add(grant.id)
        return grant

    def was_consumed(self, grant_id: str) -> bool:
        return grant_id in self._consumed

    def revoke(self, grant_id: str) -> None:
        self._issued.pop(grant_id, None)
        self._consumed.discard(grant_id)

    def _sign(self, value: dict[str, Any]) -> str:
        canonical = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hmac.new(self._secret, canonical, hashlib.sha256).hexdigest()

    @staticmethod
    def _unsigned(grant: BrowserWriteGrant) -> dict[str, Any]:
        return {
            "id": grant.id,
            "run_id": grant.run_id,
            "operation": grant.operation,
            "object_digest": grant.object_digest,
            "source_url": grant.source_url,
            "file_digests": grant.file_digests,
            "expires_at": grant.expires_at.isoformat(),
        }


__all__ = ["BrowserWriteGrant", "BrowserWriteGrantAuthority"]
