"""PostgreSQL repositories, migrations and transactional unit of work."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from webauto.config import SecretValue
from webauto.domain import GoalContract

from .uow import AbstractUnitOfWork

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class PostgresGoalRepository:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def add(self, goal: GoalContract, *, owner_id: str) -> None:
        await self._connection.execute(
            """
            INSERT INTO goals(id, owner_id, schema_version, objective, contract)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                goal.id,
                owner_id,
                goal.schema_version,
                goal.objective,
                json.dumps(goal.model_dump(mode="json"), ensure_ascii=False),
            ),
        )

    async def save(self, goal: GoalContract, *, owner_id: str) -> None:
        await self._connection.execute(
            """
            INSERT INTO goals(id, owner_id, schema_version, objective, contract)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                schema_version = EXCLUDED.schema_version,
                objective = EXCLUDED.objective,
                contract = EXCLUDED.contract,
                updated_at = now()
            """,
            (
                goal.id,
                owner_id,
                goal.schema_version,
                goal.objective,
                json.dumps(goal.model_dump(mode="json"), ensure_ascii=False),
            ),
        )


class PostgresOutboxRepository:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def add(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> str:
        event_id = str(uuid4())
        await self._connection.execute(
            """
            INSERT INTO outbox(id, aggregate_type, aggregate_id, event_type, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                event_id,
                aggregate_type,
                aggregate_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return event_id

    async def pending(self, limit: int = 100) -> list[dict[str, object]]:
        cursor = await self._connection.execute(
            """
            SELECT id, event_type, payload
            FROM outbox
            WHERE published_at IS NULL
            ORDER BY created_at
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [{"id": str(row[0]), "event_type": row[1], "payload": row[2]} for row in rows]

    async def mark_published(self, event_id: str) -> None:
        await self._connection.execute(
            "UPDATE outbox SET published_at = now(), last_error = NULL WHERE id = %s",
            (event_id,),
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        await self._connection.execute(
            """
            UPDATE outbox
            SET attempt_count = attempt_count + 1, last_error = %s
            WHERE id = %s
            """,
            (error[:1000], event_id),
        )


ConnectFactory = Callable[[str], Awaitable[Any]]


class PostgresUnitOfWork(AbstractUnitOfWork):
    def __init__(self, dsn: SecretValue, *, connect: ConnectFactory | None = None) -> None:
        self._dsn = dsn
        self._connect = connect
        self._connection: Any | None = None
        self.goals: PostgresGoalRepository | None = None
        self.outbox: PostgresOutboxRepository | None = None

    def __repr__(self) -> str:
        return f"PostgresUnitOfWork(dsn={self._dsn!r})"

    async def _open(self) -> None:
        connect = self._connect
        if connect is None:
            try:
                from psycopg import AsyncConnection
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL support requires the 'postgres' optional dependency"
                ) from exc
            connect = AsyncConnection.connect
        self._connection = await connect(self._dsn.get_secret_value())
        self.goals = PostgresGoalRepository(self._connection)
        self.outbox = PostgresOutboxRepository(self._connection)

    async def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("unit of work is not open")
        await self._connection.commit()

    async def rollback(self) -> None:
        if self._connection is not None:
            await self._connection.rollback()

    async def _close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self.goals = None
        self.outbox = None


async def apply_migrations(connection: Any, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply ordered SQL migrations using an already-authorized connection."""

    applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        await connection.execute(path.read_text(encoding="utf-8"))
        applied.append(path.stem)
    return applied
