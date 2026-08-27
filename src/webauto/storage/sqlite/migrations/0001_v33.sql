-- WebAuto v3.3 safety-critical state (B2-01).
-- Five tables only; no Outbox, no generic Repository/UoW.
-- Conventions: opaque TEXT ids, UTC epoch milliseconds, lowercase SHA-256 hex.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at_ms INTEGER NOT NULL,
    sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_leases (
    lease_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    holder_id TEXT NOT NULL,
    fencing_token TEXT NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_leases_profile ON profile_leases (profile_id);
CREATE INDEX IF NOT EXISTS idx_profile_leases_expires ON profile_leases (expires_at_ms);

CREATE TABLE IF NOT EXISTS action_attempts (
    attempt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    action_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    prepared_facts TEXT NOT NULL,        -- canonical JSON
    policy_decision_id TEXT,
    policy_version TEXT,
    optimistic_version INTEGER NOT NULL DEFAULT 1,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE (session_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_action_attempts_status ON action_attempts (status);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    action_hash TEXT NOT NULL,
    page_revision TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    object_digest TEXT NOT NULL,
    identity_digest TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,  -- bool 0/1
    resolved INTEGER NOT NULL DEFAULT 0,   -- bool 0/1
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_attempt ON approvals (attempt_id);

-- Account-safety scope: persists across Provider / network-identity switches.
-- Composite PK: (scope_type, scope_key_digest, window_start_ms).
CREATE TABLE IF NOT EXISTS behavior_budgets (
    scope_type TEXT NOT NULL,            -- 'execution' | 'account_safety'
    scope_key_digest TEXT NOT NULL,      -- sha256 of canonical (site, account_ref|profile_id)
    window_start_ms INTEGER NOT NULL,
    executions INTEGER NOT NULL DEFAULT 0,
    writes INTEGER NOT NULL DEFAULT 0,
    last_reset_ms INTEGER NOT NULL,
    cooldown_until_ms INTEGER NOT NULL DEFAULT 0,
    circuit_open_until_ms INTEGER NOT NULL DEFAULT 0,
    hits_403 INTEGER NOT NULL DEFAULT 0,
    hits_429 INTEGER NOT NULL DEFAULT 0,
    challenge_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope_type, scope_key_digest, window_start_ms)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT,
    attempt_id TEXT,
    action_type TEXT NOT NULL,
    error_code TEXT,
    evidence_ids TEXT NOT NULL DEFAULT '[]',  -- canonical JSON array
    actor TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events (session_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events (created_at_ms);
