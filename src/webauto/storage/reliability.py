"""PostgreSQL adapters for restart-safe worker and checkpoint primitives."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from webauto.config import SecretValue
from webauto.domain import PageState
from webauto.runtime.reliability import Checkpoint

ConnectFactory = Callable[[str], Awaitable[Any]]


class _PostgresStore:
    def __init__(self, dsn: SecretValue, *, connect: ConnectFactory | None = None) -> None:
        self._dsn = dsn
        self._connect = connect

    async def _open(self) -> Any:
        if self._connect is not None:
            return await self._connect(self._dsn.get_secret_value())
        try:
            from psycopg import AsyncConnection
        except ImportError as exc:
            raise RuntimeError("PostgreSQL reliability requires the 'postgres' extra") from exc
        return await AsyncConnection.connect(self._dsn.get_secret_value())


class PostgresIdempotencyStore(_PostgresStore):
    async def claim(self, key: str) -> bool:
        connection = await self._open()
        try:
            cursor = await connection.execute(
                """
                INSERT INTO idempotency_keys(id, idempotency_key, state)
                VALUES (%s, %s, 'claimed')
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                (str(uuid4()), key),
            )
            claimed = await cursor.fetchone() is not None
            await connection.commit()
            return claimed
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.close()

    async def complete(self, key: str, result: dict[str, Any]) -> None:
        connection = await self._open()
        try:
            cursor = await connection.execute(
                """
                UPDATE idempotency_keys
                SET state = 'completed', result = %s::jsonb, updated_at = now()
                WHERE idempotency_key = %s AND state = 'claimed'
                RETURNING id
                """,
                (json.dumps(result, ensure_ascii=False), key),
            )
            if await cursor.fetchone() is None:
                raise RuntimeError("idempotency key is not actively claimed")
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.close()

    async def result(self, key: str) -> dict[str, Any] | None:
        connection = await self._open()
        try:
            cursor = await connection.execute(
                """
                SELECT result FROM idempotency_keys
                WHERE idempotency_key = %s AND state = 'completed'
                """,
                (key,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        finally:
            await connection.close()

    async def abandon(self, key: str) -> None:
        connection = await self._open()
        try:
            await connection.execute(
                "DELETE FROM idempotency_keys WHERE idempotency_key = %s AND state = 'claimed'",
                (key,),
            )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.close()


class PostgresCheckpointStore(_PostgresStore):
    async def save(self, checkpoint: Checkpoint) -> None:
        connection = await self._open()
        try:
            await connection.execute(
                """
                INSERT INTO checkpoints(
                    id, run_id, plan_id, plan_version, resume_node_id,
                    verified_facts, page_state, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    checkpoint.id,
                    checkpoint.run_id,
                    checkpoint.plan_id,
                    checkpoint.plan_version,
                    checkpoint.resume_node_id,
                    json.dumps(checkpoint.verified_facts, ensure_ascii=False),
                    json.dumps(checkpoint.page_state.model_dump(mode="json"), ensure_ascii=False),
                    checkpoint.created_at,
                ),
            )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.close()

    async def latest(self, run_id: str) -> Checkpoint | None:
        connection = await self._open()
        try:
            cursor = await connection.execute(
                """
                SELECT id, plan_id, plan_version, resume_node_id,
                       verified_facts, page_state, created_at
                FROM checkpoints WHERE run_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            facts = row[4] if isinstance(row[4], dict) else json.loads(row[4])
            page = row[5] if isinstance(row[5], dict) else json.loads(row[5])
            return Checkpoint(
                id=str(row[0]),
                run_id=run_id,
                plan_id=str(row[1]),
                plan_version=row[2],
                resume_node_id=row[3],
                verified_facts=facts,
                page_state=PageState.model_validate(page),
                created_at=row[6],
            )
        finally:
            await connection.close()
