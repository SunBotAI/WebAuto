BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS goals (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    schema_version VARCHAR(16) NOT NULL,
    objective TEXT NOT NULL,
    contract JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    placement VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL,
    fencing_token BIGINT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY,
    goal_id UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    schema_version VARCHAR(16) NOT NULL,
    graph JSONB NOT NULL,
    candidate JSONB NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY,
    goal_id UUID NOT NULL REFERENCES goals(id),
    plan_id UUID REFERENCES plans(id),
    profile_id UUID REFERENCES profiles(id),
    state VARCHAR(32) NOT NULL,
    placement VARCHAR(32) NOT NULL,
    fencing_token BIGINT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS run_steps (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    node_id VARCHAR(255) NOT NULL,
    sequence INTEGER NOT NULL,
    state VARCHAR(32) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    input JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, sequence)
);

CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_id UUID REFERENCES run_steps(id) ON DELETE CASCADE,
    action_hash VARCHAR(128) NOT NULL,
    profile_id UUID REFERENCES profiles(id),
    placement VARCHAR(32) NOT NULL,
    risk_level VARCHAR(2) NOT NULL,
    preview JSONB NOT NULL,
    diff JSONB NOT NULL,
    state VARCHAR(32) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_events (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    kind VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, sequence)
);

CREATE TABLE IF NOT EXISTS outbox (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS goals_owner_idx ON goals(owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runs_state_idx ON runs(state, updated_at);
CREATE INDEX IF NOT EXISTS approvals_pending_idx ON approvals(state, expires_at);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON outbox(created_at) WHERE published_at IS NULL;

INSERT INTO schema_migrations(version) VALUES ('0001_initial')
ON CONFLICT (version) DO NOTHING;

COMMIT;
