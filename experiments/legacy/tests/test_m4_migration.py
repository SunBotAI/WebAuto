"""M4 PostgreSQL persistence schema contract."""

from webauto.storage import MIGRATIONS_DIR


def test_reliability_migration_covers_durable_runtime_objects() -> None:
    sql = (MIGRATIONS_DIR / "0002_reliability.sql").read_text(encoding="utf-8").lower()
    for table in (
        "checkpoints",
        "scheduled_jobs",
        "artifacts",
        "worker_heartbeats",
        "idempotency_keys",
        "profile_leases",
    ):
        assert f"create table if not exists {table}" in sql
    assert "fencing_token" in sql
    assert "unique (dedupe_key)" in sql
    assert "unique (idempotency_key)" in sql


def test_application_state_migration_supports_restart_and_optimistic_writes() -> None:
    sql = (MIGRATIONS_DIR / "0003_application_state.sql").read_text(encoding="utf-8").lower()
    assert "create table if not exists application_state" in sql
    assert "revision bigint" in sql
    assert "payload jsonb" in sql
