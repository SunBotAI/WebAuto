"""Local single-user session authentication for the WebAuto control plane."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .service import Actor, Role


class LocalSessionError(RuntimeError):
    """Raised when a local session or CSRF proof is missing or invalid."""


@dataclass(frozen=True, slots=True)
class IssuedLocalSession:
    token: str
    csrf_token: str
    expires_at: datetime
    actor: Actor


class LocalSessionManager:
    """Issue stateless, HMAC-signed sessions backed by a local private key."""

    cookie_name = "webauto_session"

    def __init__(
        self,
        key_path: Path,
        *,
        ttl: timedelta = timedelta(hours=8),
        clock: Any | None = None,
    ) -> None:
        if ttl.total_seconds() <= 0:
            raise ValueError("session ttl must be positive")
        self.key_path = key_path
        self.ttl = ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._key = self._load_or_create_key()

    def issue(self) -> IssuedLocalSession:
        now = self._clock()
        expires_at = now + self.ttl
        csrf_token = secrets.token_urlsafe(24)
        payload = {
            "version": 1,
            "subject": "local-user",
            "tenant": "local",
            "roles": [Role.ADMIN.value],
            "issued_at": int(now.timestamp()),
            "expires_at": int(expires_at.timestamp()),
            "csrf": csrf_token,
            "nonce": secrets.token_urlsafe(16),
        }
        encoded = _encode_json(payload)
        signature = _encode_bytes(hmac.new(self._key, encoded.encode(), hashlib.sha256).digest())
        actor = Actor("local-user", "local", {Role.ADMIN})
        return IssuedLocalSession(f"{encoded}.{signature}", csrf_token, expires_at, actor)

    def authenticate(self, token: str | None) -> Actor:
        payload = self._verify(token)
        try:
            roles = {Role(value) for value in payload["roles"]}
            return Actor(str(payload["subject"]), str(payload["tenant"]), roles)
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalSessionError("local session identity is invalid") from exc

    def csrf_token(self, token: str | None) -> str:
        payload = self._verify(token)
        csrf = payload.get("csrf")
        if not isinstance(csrf, str) or not csrf:
            raise LocalSessionError("local session has no CSRF proof")
        return csrf

    def verify_csrf(self, token: str | None, supplied: str | None) -> None:
        expected = self.csrf_token(token)
        if not supplied or not hmac.compare_digest(expected, supplied):
            raise LocalSessionError("valid CSRF token required")

    def _verify(self, token: str | None) -> dict[str, Any]:
        if not token or token.count(".") != 1:
            raise LocalSessionError("valid local session required")
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _encode_bytes(
            hmac.new(self._key, encoded.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise LocalSessionError("local session signature is invalid")
        try:
            payload = json.loads(_decode_bytes(encoded).decode("utf-8"))
            expires_at = datetime.fromtimestamp(int(payload["expires_at"]), timezone.utc)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LocalSessionError("local session payload is invalid") from exc
        if payload.get("version") != 1 or self._clock() >= expires_at:
            raise LocalSessionError("local session is expired or unsupported")
        return payload

    def _load_or_create_key(self) -> bytes:
        configured = os.environ.get("WEBAUTO_SESSION_KEY")
        if configured:
            return hashlib.sha256(configured.encode("utf-8")).digest()
        if self.key_path.exists():
            value = self.key_path.read_bytes()
            if len(value) < 32:
                raise RuntimeError("local session key must contain at least 32 bytes")
            return value
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_bytes(32)
        self.key_path.write_bytes(value)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return value


def _encode_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _encode_bytes(raw.encode("utf-8"))


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
