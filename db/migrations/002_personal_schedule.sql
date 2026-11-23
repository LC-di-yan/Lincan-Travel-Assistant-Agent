-- Additive schedule migration; run after 001_personal_trips.sql.
BEGIN;
CREATE TABLE IF NOT EXISTS personal_plan_state (
    user_id VARCHAR(64) PRIMARY KEY REFERENCES users(user_id),
    calendar_revision INTEGER NOT NULL DEFAULT 0 CHECK (calendar_revision >= 0),
    state JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS trip_schedule_blocks (
    user_id VARCHAR(64) NOT NULL,
    plan_id UUID NOT NULL,
    version_no INTEGER NOT NULL,
    block_id UUID NOT NULL,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    local_date DATE,
    payload JSONB NOT NULL,
    PRIMARY KEY (user_id, plan_id, block_id),
    FOREIGN KEY (user_id, plan_id, version_no) REFERENCES trip_plan_versions (user_id, plan_id, version_no),
    CHECK ((start_at IS NULL AND end_at IS NULL) OR (start_at IS NOT NULL AND end_at IS NOT NULL AND start_at < end_at))
);
CREATE INDEX IF NOT EXISTS idx_trip_schedule_user_time ON trip_schedule_blocks (user_id, start_at);
CREATE INDEX IF NOT EXISTS idx_trip_schedule_user_date ON trip_schedule_blocks (user_id, local_date);
COMMIT;
