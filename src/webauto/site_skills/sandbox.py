"""Static sandbox for declarative Site Skill payloads."""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlparse


class SkillSandbox:
    _secret_keys: ClassVar[set[str]] = {
        "secret",
        "secrets",
        "token",
        "access_token",
        "refresh_token",
        "cookie",
        "cookies",
        "password",
        "authorization",
        "database_url",
    }
    _script_keys: ClassVar[set[str]] = {
        "script",
        "python",
        "javascript",
        "shell",
        "command",
        "sql",
    }

    def validate_payload(
        self, payload: Any, *, allowed_hosts: set[str] | None = None, path: str = "$"
    ) -> None:
        if isinstance(payload, dict):
            kind = str(payload.get("kind", "")).lower()
            if kind in {"evaluate", "script", "shell", "sql"}:
                raise ValueError(f"script execution is forbidden at {path}")
            for key, value in payload.items():
                lowered = str(key).lower()
                if lowered in self._secret_keys:
                    raise ValueError(f"secret field is forbidden at {path}.{key}")
                if lowered in self._script_keys:
                    raise ValueError(f"script field is forbidden at {path}.{key}")
                self.validate_payload(value, allowed_hosts=allowed_hosts, path=f"{path}.{key}")
            return
        if isinstance(payload, list):
            for index, value in enumerate(payload):
                self.validate_payload(value, allowed_hosts=allowed_hosts, path=f"{path}[{index}]")
            return
        if isinstance(payload, str) and payload.startswith(("http://", "https://")):
            host = urlparse(payload).hostname
            if allowed_hosts is not None and host not in allowed_hosts:
                raise ValueError(f"network host {host} is outside the skill sandbox")
