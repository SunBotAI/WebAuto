"""Runtime configuration with explicit secret and filesystem boundaries."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class SecretValue:
    """Small dependency-free secret wrapper with a redacted representation."""

    __slots__ = ("_value",)

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "SecretValue('********')" if self._value else "SecretValue('')"


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Infrastructure settings shared by API, workers and local execution."""

    project_root: Path
    runtime_dir: Path
    database_url: SecretValue = field(default_factory=SecretValue)
    redis_url: SecretValue = field(default_factory=SecretValue)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        project_root: Path | None = None,
    ) -> RuntimeSettings:
        values = os.environ if env is None else env
        root = (project_root or Path.cwd()).resolve()
        configured_runtime = Path(values.get("WEBAUTO_RUNTIME_DIR", "var"))
        runtime_dir = (
            configured_runtime if configured_runtime.is_absolute() else root / configured_runtime
        )
        return cls(
            project_root=root,
            runtime_dir=runtime_dir,
            database_url=SecretValue(values.get("WEBAUTO_DATABASE_URL", "")),
            redis_url=SecretValue(values.get("WEBAUTO_REDIS_URL", "")),
        )
