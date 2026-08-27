"""Outcome reconciliation primitives.

Per plan §7.5, ``OutcomeReconciler.reconcile`` returns one of three
authoritative states after a non-idempotent write attempt:

* ``COMMITTED`` — the external system confirms the write.
* ``NOT_COMMITTED_AUTHORITATIVE`` — a definitive query shows the
  write never reached the external system.
* ``INCONCLUSIVE`` — the query path failed; the caller must not retry
  the write and must report the state to the user.

The Protocol lives here so storage-layer repos and mcp_browser-layer
executor can share the same types without coupling to each other.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class ReconcileResult(str, Enum):
    COMMITTED = "committed"
    NOT_COMMITTED_AUTHORITATIVE = "not_committed_authoritative"
    INCONCLUSIVE = "inconclusive"


class OutcomeReconciler(Protocol):
    """Authoritative post-write query interface."""

    async def reconcile(
        self,
        business_key: dict[str, Any],
        prepared_facts: dict[str, Any],
    ) -> ReconcileResult: ...
