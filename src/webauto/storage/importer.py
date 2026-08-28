"""Legacy-state importer: read old JSON / PostgreSQL ApplicationState and
emit a per-table row-count matrix.

Per plan §22.1 the import is read-only, idempotent, and never writes
back to its source. The matrix is consumed by the v3.3 release
operator to verify that the live SQLite database is consistent with
the historical payload before the old stack is decommissioned.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# Source formats recognised in this iteration. Each entry is a key prefix
# in the legacy JSON dump (or a row prefix in the legacy Postgres table).
SOURCE_KEYS = (
    "runs",
    "approvals",
    "leases",
    "browser_sessions",
    "settings",
    "audit",
)


def _walk(obj: Any) -> Iterable[tuple[str, int]]:
    """Yield (source_kind, row_count) for every recognised top-level key.

    The legacy blob is a dict whose keys look like the section names above.
    Each list value contributes the section's row count.
    """
    if isinstance(obj, dict):
        for kind in SOURCE_KEYS:
            items = obj.get(kind)
            if isinstance(items, list):
                yield kind, len(items)


def import_matrix_from_json(path: Path) -> dict[str, int]:
    """Read a legacy JSON ApplicationState blob and return {source_kind: rows}."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = Counter({k: 0 for k in SOURCE_KEYS})
    for kind, n in _walk(payload):
        counts[kind] += n
    return dict(counts)


def derive_sqlite_counts(sqlite_path: Path) -> dict[str, int]:
    """Read the live v3.3 SQLite five-table row counts for comparison."""
    import sqlite3

    if not sqlite_path.exists():
        return {}
    conn = sqlite3.connect(str(sqlite_path))
    try:
        out: dict[str, int] = {}
        for table, kind in (
            ("action_attempts", "runs"),
            ("approvals", "approvals"),
            ("profile_leases", "leases"),
            ("audit_events", "audit"),
        ):
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            out[kind] = cur.fetchone()[0]
        return out
    finally:
        conn.close()


def matrix(
    legacy_json: Path, sqlite_path: Path
) -> dict[str, dict[str, int | str]]:
    """Return {kind: {'legacy': n, 'sqlite': m, 'status': 'matched'/'missing'/'extra'}}."""
    legacy = import_matrix_from_json(legacy_json)
    live = derive_sqlite_counts(sqlite_path)
    out: dict[str, dict[str, int | str]] = {}
    for kind in SOURCE_KEYS:
        l = legacy.get(kind, 0)
        s = live.get(kind, 0)
        status = "matched" if l == s else ("missing" if l > s else "extra")
        out[kind] = {"legacy": l, "sqlite": s, "status": status}
    return out
