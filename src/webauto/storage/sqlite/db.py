"""SQLite connection and schema bootstrap for the v3.3 safety-critical state.

Only the schema-version pragma, WAL, foreign keys and busy-timeout are
configured. Application code opens the connection, sets ``isolation_level=None``
to manage transactions explicitly via ``BEGIN IMMEDIATE``, and closes the
handle in its own scope.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
LATEST_VERSION = "0001_v33"


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (and bootstrap schema for) the safety-critical SQLite database."""
    db_path = Path(path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply the latest schema migration if not already applied."""
    conn.executescript(
        (MIGRATIONS_DIR / f"{LATEST_VERSION}.sql").read_text(encoding="utf-8")
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at_ms, sha256) "
        "VALUES (?, CAST(? AS INTEGER), ?)",
        (
            LATEST_VERSION,
            _now_ms(),
            _schema_sha256(),
        ),
    )


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _schema_sha256() -> str:
    import hashlib

    content = (MIGRATIONS_DIR / f"{LATEST_VERSION}.sql").read_bytes()
    return hashlib.sha256(content).hexdigest()
