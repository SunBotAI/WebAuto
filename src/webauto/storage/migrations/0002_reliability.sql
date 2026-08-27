BEGIN;

CREATE TABLE IF NOT EXISTS checkpoints (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES plans(id),
    plan_version VARCHAR(32) NOT NULL,
    resume_node_id VARCHAR(255) NOT NULL,
    verified_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    page_state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id UUID PRIMARY KEY,
    dedupe_key VARCHAR(255) NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'scheduled',
    misfire_policy VARCHAR(32) NOT NULL DEFAULT 'grace',
    dispatched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dedupe_key)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    run_id UUID REFERENCES runs(id) ON DELETE CASCADE,
    media_type VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    redaction_state VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id VARCHAR(255) PRIMARY KEY,
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id UUID PRIMARY KEY,
    idempotency_key VARCHAR(512) NOT NULL,
    state VARCHAR(32) NOT NULL,
    result JSONB,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (idempotency_key)
);

CREATE TABLE IF NOT EXISTS profile_leases (
    profile_id UUID PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    lease_id UUID NOT NULL,
    holder_id VARCHAR(255) NOT NULL,
    placement VARCHAR(32) NOT NULL,
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_id, fencing_token)
);

CREATE TABLE IF NOT EXISTS run_control_commands (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS checkpoints_run_idx ON checkpoints(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS scheduled_jobs_due_idx ON scheduled_jobs(state, due_at);
CREATE INDEX IF NOT EXISTS artifacts_expiry_idx ON artifacts(expires_at);
CREATE INDEX IF NOT EXISTS worker_heartbeats_seen_idx ON worker_heartbeats(observed_at);
CREATE INDEX IF NOT EXISTS run_control_pending_idx
    ON run_control_commands(run_id, created_at) WHERE consumed_at IS NULL;

INSERT INTO schema_migrations(version) VALUES ('0002_reliability')
ON CONFLICT (version) DO NOTHING;

COMMIT;
