-- Additive migration. Requires db/schema.sql first; no existing rows are changed.
BEGIN;
CREATE TABLE IF NOT EXISTS trip_plans (
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id),
    plan_id UUID NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('draft','scheduled','completed','cancelled','superseded','archived')),
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (user_id, plan_id)
);
CREATE INDEX IF NOT EXISTS idx_trip_plans_user_updated ON trip_plans (user_id, updated_at DESC, plan_id);
CREATE TABLE IF NOT EXISTS trip_plan_versions (
    user_id VARCHAR(64) NOT NULL,
    plan_id UUID NOT NULL,
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    parent_version_no INTEGER,
    payload JSONB NOT NULL,
    PRIMARY KEY (user_id, plan_id, version_no),
    FOREIGN KEY (user_id, plan_id) REFERENCES trip_plans (user_id, plan_id),
    FOREIGN KEY (user_id, plan_id, parent_version_no) REFERENCES trip_plan_versions (user_id, plan_id, version_no),
    CHECK (parent_version_no IS NULL OR parent_version_no < version_no)
);
CREATE TABLE IF NOT EXISTS trip_plan_operations (
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id),
    operation_key VARCHAR(180) NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (user_id, operation_key)
);
COMMIT;
