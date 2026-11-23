-- Personal choices reuse preferences and personal_plan_state; only bookmarks need a new table.
BEGIN;
CREATE TABLE IF NOT EXISTS personal_favorites (
    user_id VARCHAR(64) NOT NULL,
    favorite_id UUID NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('plan','rail','hotel','place')),
    dedupe_key CHAR(64) NOT NULL,
    plan_id UUID NOT NULL,
    version_no INTEGER NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (user_id, favorite_id),
    UNIQUE (user_id, kind, dedupe_key),
    FOREIGN KEY (user_id, plan_id, version_no) REFERENCES trip_plan_versions(user_id, plan_id, version_no)
);
COMMIT;
