"""PostgreSQL adapter for the application-state port."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from webauto.application.state import ApplicationStateStore
from webauto.config import SecretValue

ConnectFactory = Callable[[str], Awaitable[Any]]


class PostgresApplicationStateStore(ApplicationStateStore):
    """PostgreSQL snapshot store with optimistic revision checks."""

    def __init__(self, dsn: SecretValue, *, connect: ConnectFactory | None = None) -> None:
        self._dsn = dsn
        self._connect = connect
        self._revision: int | None = None

    async def _open(self) -> Any:
        if self._connect is not None:
            return await self._connect(self._dsn.get_secret_value())
        try:
            from psycopg import AsyncConnection
        except ImportError as exc:
            raise RuntimeError("PostgreSQL state requires the 'postgres' extra") from exc
        return await AsyncConnection.connect(self._dsn.get_secret_value())

    async def load(self) -> dict[str, Any] | None:
        connection = await self._open()
        try:
            cursor = await connection.execute(
                "SELECT revision, payload FROM application_state WHERE state_key = %s",
                ("control-plane",),
            )
            row = await cursor.fetchone()
            if row is None:
                self._revision = 0
                return None
            self._revision = int(row[0])
            return row[1] if isinstance(row[1], dict) else json.loads(row[1])
        finally:
            await connection.close()

    async def save(self, state: dict[str, Any]) -> None:
        connection = await self._open()
        try:
            expected = 0 if self._revision is None else self._revision
            if expected == 0:
                cursor = await connection.execute(
                    """
                    INSERT INTO application_state(state_key, revision, payload)
                    VALUES (%s, 1, %s::jsonb)
                    ON CONFLICT (state_key) DO NOTHING
                    RETURNING revision
                    """,
                    ("control-plane", json.dumps(state, ensure_ascii=False)),
                )
            else:
                cursor = await connection.execute(
                    """
                    UPDATE application_state
                    SET revision = revision + 1, payload = %s::jsonb, updated_at = now()
                    WHERE state_key = %s AND revision = %s
                    RETURNING revision
                    """,
                    (json.dumps(state, ensure_ascii=False), "control-plane", expected),
                )
            row = await cursor.fetchone()
            if row is None:
                await connection.rollback()
                raise RuntimeError("application state changed concurrently; reload and retry")
            await connection.commit()
            self._revision = int(row[0])
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.close()
