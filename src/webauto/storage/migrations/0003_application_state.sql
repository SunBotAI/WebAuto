BEGIN;

CREATE TABLE IF NOT EXISTS application_state (
    state_key VARCHAR(128) PRIMARY KEY,
    revision BIGINT NOT NULL CHECK (revision > 0),
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations(version) VALUES ('0003_application_state')
ON CONFLICT (version) DO NOTHING;

COMMIT;
