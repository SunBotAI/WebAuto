"""Persistence boundary tests that do not require a live database."""

from pathlib import Path

import pytest

from webauto.storage import MIGRATIONS_DIR, AbstractUnitOfWork


def test_initial_postgres_migration_contains_required_tables() -> None:
    sql = (MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8").lower()

    required = {
        "schema_migrations",
        "goals",
        "plans",
        "runs",
        "run_steps",
        "profiles",
        "approvals",
        "outbox",
        "agent_events",
    }
    for table in required:
        assert f"create table if not exists {table}" in sql

    assert "jsonb" in sql
    assert "unique (run_id, sequence)" in sql
    assert "outbox_unpublished_idx" in sql


def test_migrations_directory_is_packaged_under_storage() -> None:
    assert MIGRATIONS_DIR == Path(__file__).parents[2] / "src/webauto/storage/migrations"


class RecordingUnitOfWork(AbstractUnitOfWork):
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def _open(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def _close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_unit_of_work_commits_on_success() -> None:
    uow = RecordingUnitOfWork()

    async with uow:
        pass

    assert uow.commits == 1
    assert uow.rollbacks == 0


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_on_exception() -> None:
    uow = RecordingUnitOfWork()

    with pytest.raises(RuntimeError):
        async with uow:
            raise RuntimeError("boom")

    assert uow.commits == 0
    assert uow.rollbacks == 1
