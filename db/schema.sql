-- Aligo 智能旅行助手 - PostgreSQL Schema
-- 执行方式: psql -U aligo -d aligo -f db/schema.sql

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    user_id     VARCHAR(64) PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    query_count BIGINT NOT NULL DEFAULT 0
);

-- 用户偏好（每条偏好一行，支持 append/replace）
CREATE TABLE IF NOT EXISTS preferences (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    pref_type   VARCHAR(64) NOT NULL,
    pref_value  JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, pref_type)
);
CREATE INDEX IF NOT EXISTS idx_preferences_user ON preferences(user_id);

-- 聊天记录
CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id  VARCHAR(32),
    role        VARCHAR(16) NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_user_time ON chat_messages(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(user_id, session_id);

-- 行程记录
CREATE TABLE IF NOT EXISTS trip_history (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    trip_id         VARCHAR(32) NOT NULL,
    origin          VARCHAR(128),
    destination     VARCHAR(128),
    start_date      DATE,
    end_date        DATE,
    purpose         VARCHAR(64),
    extra           JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trip_user ON trip_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trip_dest ON trip_history(user_id, destination);

-- 费用记录
CREATE TABLE IF NOT EXISTS expenses (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expense_id  VARCHAR(32) NOT NULL,
    category    VARCHAR(32) NOT NULL,
    amount      NUMERIC(12,2) NOT NULL,
    currency    VARCHAR(8) DEFAULT 'CNY',
    description TEXT,
    expense_date DATE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_expense_user_time ON expenses(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_expense_user_cat ON expenses(user_id, category);

-- 插件配置
CREATE TABLE IF NOT EXISTS plugin_config (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plugin_name     VARCHAR(64) NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, plugin_name)
);
CREATE INDEX IF NOT EXISTS idx_plugin_user ON plugin_config(user_id);
