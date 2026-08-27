"""Standard-library sqlite3 storage for the v3.3 safety-critical state.

Five tables only (Lease / ActionAttempt / Approval / Budget / Audit).
No Outbox, no generic Repository / UoW. Uses :memory: for tests and
``var/webauto.db`` for the local Daemon / MCP process. Cross-process
synchronisation relies on SQLite row-level transactions + fencing tokens;
see ``webauto.runtime.browser.lease`` for the lease primitive.
"""
