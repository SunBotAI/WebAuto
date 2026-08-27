"""PostgreSQL adapter tests with a connection double."""

import pytest

from webauto.config import SecretValue
from webauto.storage.postgres import PostgresUnitOfWork, apply_migrations


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.statements: list[str] = []

    async def execute(self, sql: str, parameters=None):
        self.statements.append(sql)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


@pytest.mark.asyncio
async def test_postgres_uow_uses_one_connection_and_redacts_dsn() -> None:
    connection = FakeConnection()

    async def connect(dsn: str):
        assert dsn == "postgresql://user:password@localhost/webauto"
        return connection

    uow = PostgresUnitOfWork(
        SecretValue("postgresql://user:password@localhost/webauto"),
        connect=connect,
    )
    assert "password" not in repr(uow)

    async with uow:
        assert uow.goals is not None
        assert uow.outbox is not None

    assert connection.commits == 1
    assert connection.closes == 1


@pytest.mark.asyncio
async def test_apply_migrations_executes_versioned_sql() -> None:
    connection = FakeConnection()

    applied = await apply_migrations(connection)

    assert applied == ["0001_initial", "0002_reliability", "0003_application_state"]
    assert "create table if not exists goals" in connection.statements[0].lower()
