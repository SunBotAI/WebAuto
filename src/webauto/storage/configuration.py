"""Infrastructure diagnostics and initialization for the configuration center."""

from __future__ import annotations

from typing import Any


def test_postgres(dsn: str) -> dict[str, Any]:
    if not dsn:
        return {"ok": False, "message": "未配置 PostgreSQL；开发模式可使用 JSON"}
    try:
        import psycopg

        with (
            psycopg.connect(dsn, connect_timeout=3) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"ok": True, "message": "PostgreSQL 连接成功"}
    except ImportError:
        return {"ok": False, "message": "未安装 postgres 可选依赖"}
    except Exception as exc:  # noqa: BLE001 - database driver diagnostic boundary
        return {"ok": False, "message": f"PostgreSQL 连接失败：{type(exc).__name__}"}


async def initialize_postgres(dsn: str) -> dict[str, Any]:
    if not dsn:
        raise ValueError("PostgreSQL DSN is not configured")
    try:
        from psycopg import AsyncConnection
    except ImportError as exc:
        raise RuntimeError("PostgreSQL support requires the 'postgres' extra") from exc
    from .postgres import apply_migrations

    connection = await AsyncConnection.connect(dsn, connect_timeout=5)
    try:
        applied = await apply_migrations(connection)
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    return {"ok": True, "applied": applied, "restart_required": True}
