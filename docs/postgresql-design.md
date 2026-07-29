# PostgreSQL 引入设计方案（修订版）

> **版本**: v2.1 | **日期**: 2026-07-28 | **状态**: 设计阶段

## 〇、ER 图

```
┌──────────────┐       ┌───────────────────┐       ┌──────────────────┐
│    users     │       │   preferences     │       │  chat_messages   │
├──────────────┤       ├───────────────────┤       ├──────────────────┤
│ PK user_id   │──┐    │ PK id (serial)    │       │ PK id (bigserial)│
│    created_at │  ├───▶│ FK user_id        │       │ FK user_id       │
│    updated_at │  │    │    pref_type (uq) │       │    session_id    │
│    query_count│  │    │    pref_value JSON│       │    role          │
└──────────────┘  │    │    created_at     │       │    content TEXT   │
                  │    │    updated_at     │       │    created_at    │
                  │    └───────────────────┘       └──────────────────┘
                  │
                  │    ┌───────────────────┐       ┌──────────────────┐
                  │    │  trip_history     │       │    expenses      │
                  │    ├───────────────────┤       ├──────────────────┤
                  ├───▶│ PK id (serial)    │       │ PK id (serial)   │
                  │    │ FK user_id        │       │ FK user_id       │
                  │    │    trip_id        │       │    expense_id    │
                  │    │    origin         │       │    category      │
                  │    │    destination    │       │    amount NUMERIC│
                  │    │    start_date     │       │    currency      │
                  │    │    end_date       │       │    description   │
                  │    │    purpose        │       │    expense_date  │
                  │    │    extra JSONB    │       │    created_at    │
                  │    │    created_at     │       └──────────────────┘
                  │    └───────────────────┘
                  │
                  │    ┌───────────────────┐
                  │    │  plugin_config    │
                  │    ├───────────────────┤
                  └───▶│ PK id (serial)    │
                       │ FK user_id        │
                       │    plugin_name (uq)│
                       │    enabled BOOLEAN│
                       │    updated_at     │
                       └───────────────────┘

  users 1──N preferences      (CASCADE DELETE)
  users 1──N chat_messages     (CASCADE DELETE)
  users 1──N trip_history      (CASCADE DELETE)
  users 1──N expenses          (CASCADE DELETE)
  users 1──N plugin_config     (CASCADE DELETE)
```

## 一、现状分析

### 当前存储架构

```
data/memory/{user_id}.json   ← LongTermMemory，单文件存所有数据
data/plugin_config.json      ← 插件启用/禁用配置
内存 dict (_sessions)         ← SessionManager，进程级缓存
```

每个用户的 JSON 文件结构：

```json
{
  "user_id": "default_user",
  "preferences": [{"type": "home_location", "value": "天津"}, ...],
  "chat_history": [{"role": "user", "content": "...", "timestamp": "...", "session_id": "..."}, ...],
  "trip_history": [{"trip_id": "trip_1", "origin": "...", "destination": "...", ...}, ...],
  "expenses": [{"id": "exp_1", "category": "餐饮", "amount": 80, ...}, ...],
  "statistics": {"total_trips": 0, "total_messages": 0, "total_queries": 0, "frequent_destinations": {}}
}
```

### 痛点

| 问题 | 影响 |
|------|------|
| 无并发安全 | 多请求同时写同一 JSON 文件会数据丢失 |
| 无查询能力 | "查本月餐饮花费"需全量加载后 Python 过滤 |
| 写回缓存 + atexit flush | 进程崩溃丢数据 |
| 无水平扩展能力 | 多实例部署时各自持独立文件，数据不共享 |
| statistics 与数据分离 | 统计字段需手动维护一致性 |

---

## 二、目标

1. 用 PostgreSQL 替换 JSON 文件存储，保持 API 接口不变。
2. `LongTermMemory` 内部从文件读写改为 SQL 操作，对外暴露相同方法签名（方法本身改为 `async`）。
3. 支持并发安全、事务、索引查询。
4. 平滑迁移：保留 JSON 导入能力，支持按环境变量回退。

**重要前提**：PostgreSQL 方案把长期记忆接口从**同步**改为**异步**。这会导致所有调用 `memory_manager.long_term.xxx()` 的代码都需要加 `await`，影响范围比初版设计更广。

---

## 三、数据库设计

### 3.1 表结构

```sql
-- 用户表
CREATE TABLE users (
    user_id     VARCHAR(64) PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 用户偏好（每条偏好一行，支持 append/replace）
CREATE TABLE preferences (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    pref_type   VARCHAR(64) NOT NULL,       -- home_location / hotel_brands / airlines ...
    pref_value  JSONB NOT NULL,             -- 字符串、字符串数组均存 JSONB
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, pref_type)
);
CREATE INDEX idx_preferences_user ON preferences(user_id);

-- 聊天记录
CREATE TABLE chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id  VARCHAR(32),
    role        VARCHAR(16) NOT NULL,       -- user / assistant / system
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_chat_user_time ON chat_messages(user_id, created_at DESC);
CREATE INDEX idx_chat_session ON chat_messages(user_id, session_id);

-- 行程记录
CREATE TABLE trip_history (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    trip_id         VARCHAR(32) NOT NULL,
    origin          VARCHAR(128),
    destination     VARCHAR(128),
    start_date      DATE,
    end_date        DATE,
    purpose         VARCHAR(64),
    extra           JSONB DEFAULT '{}',     -- 其他字段兜底
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_trip_user ON trip_history(user_id, created_at DESC);
CREATE INDEX idx_trip_dest ON trip_history(user_id, destination);

-- 费用记录
CREATE TABLE expenses (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expense_id  VARCHAR(32) NOT NULL,       -- 业务 ID，如 exp_1
    category    VARCHAR(32) NOT NULL,       -- 交通/餐饮/住宿/通讯/办公/娱乐/其他
    amount      NUMERIC(12,2) NOT NULL,
    currency    VARCHAR(8) DEFAULT 'CNY',
    description TEXT,
    expense_date DATE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_expense_user_time ON expenses(user_id, created_at DESC);
CREATE INDEX idx_expense_user_cat ON expenses(user_id, category);

-- 插件配置（从 data/plugin_config.json 迁移）
CREATE TABLE plugin_config (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plugin_name     VARCHAR(64) NOT NULL,       -- ask-question / expense-tracker / ...
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, plugin_name)
);
CREATE INDEX idx_plugin_user ON plugin_config(user_id);
```

### 3.2 设计决策说明

**preferences 用独立行而非 jsonb 列存整个用户偏好：**
- 当前代码 `save_preference(pref_type, value)` 是按类型 upsert，独立行天然支持。
- `UNIQUE(user_id, pref_type)` 保证幂等，`ON CONFLICT` 替代手动查找替换。
- `pref_value` 用 JSONB 而非 TEXT，因为 value 可能是字符串或字符串数组（如 `hotel_brands`）。

**chat_messages 不做 LIMIT 硬限制：**
- 当前 JSON 文件会无限增长，迁移后同理。
- 查询时由应用层传 `LIMIT`，数据库负责排序和索引。
- 未来可加分区或定期归档。

**statistics 不单独建表：**
- `total_trips` = `COUNT(*) FROM trip_history WHERE user_id = ?`
- `total_messages` = `COUNT(*) FROM chat_messages WHERE user_id = ?`
- `total_queries` 保留在应用层计数（原 JSON 有该字段，避免 API 不兼容）。
- `frequent_destinations` = `SELECT destination, COUNT(*) FROM trip_history GROUP BY destination ORDER BY count DESC`
- 实时计算，无需维护一致性。

**expenses.expense_id / trip_history.trip_id 保留业务 ID：**
- 当前代码用 `exp_{n}`、`trip_{n}` 作为业务 ID，迁移后继续由应用层自动生成，保持 API 返回值一致。
- 数据库主键用自增 `id`，业务 ID 仅做展示和兼容。

---

## 四、代码改造方案

### 4.1 新增文件

```
db/
├── __init__.py
├── connection.py       # 连接池管理（asyncpg）
├── schema.sql          # DDL 脚本
└── migrate.py          # JSON → PostgreSQL 数据迁移脚本
```

### 4.2 改造文件

#### `db/connection.py` — 连接池（带初始化锁）

```python
import asyncio
import asyncpg
from config import DATABASE_URL

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool | None:
    """获取连接池；如果未配置 DATABASE_URL 则返回 None，走 JSON 文件回退。"""
    if not DATABASE_URL:
        return None

    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
```

#### `context/long_term_memory.py` — 核心改造

**策略：新建 `PostgresLongTermMemory` 类，与原 `LongTermMemory` 实现相同接口，但方法均为 `async`。**

> 注意：`__init__` 不能是协程，因此 `_ensure_user()` 改为在首次数据库操作时懒加载，或通过工厂方法创建。

```python
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


class PostgresLongTermMemory:
    """基于 PostgreSQL 的长期记忆实现（异步接口）。"""

    def __init__(self, user_id: str, pool: asyncpg.Pool):
        self.user_id = user_id
        self.pool = pool
        self._user_ensured = False

    async def _ensure_user(self):
        """确保用户记录存在（懒加载）。"""
        if self._user_ensured:
            return
        await self.pool.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            self.user_id,
        )
        self._user_ensured = True

    # ---- 偏好 ----

    async def save_preference(self, pref_type: str, value: Any):
        await self._ensure_user()
        await self.pool.execute("""
            INSERT INTO preferences(user_id, pref_type, pref_value)
            VALUES($1, $2, $3::jsonb)
            ON CONFLICT(user_id, pref_type)
            DO UPDATE SET pref_value = $3::jsonb, updated_at = NOW()
        """, self.user_id, pref_type, json.dumps(value, ensure_ascii=False))

    async def get_preference(self, pref_type: str = None) -> Any:
        await self._ensure_user()
        if pref_type:
            row = await self.pool.fetchrow(
                "SELECT pref_value FROM preferences WHERE user_id=$1 AND pref_type=$2",
                self.user_id, pref_type
            )
            return row["pref_value"] if row else None
        else:
            rows = await self.pool.fetch(
                "SELECT pref_type, pref_value FROM preferences WHERE user_id=$1",
                self.user_id
            )
            return {r["pref_type"]: r["pref_value"] for r in rows}

    async def add_hotel_brand(self, brand: str):
        """原子追加：用 SQL JSONB 操作避免读-写竞态。"""
        await self._ensure_user()
        await self.pool.execute("""
            INSERT INTO preferences(user_id, pref_type, pref_value)
            VALUES($1, 'hotel_brands', $2::jsonb)
            ON CONFLICT(user_id, pref_type) DO UPDATE SET
                pref_value = (
                    CASE WHEN preferences.pref_value::jsonb ? $3
                         THEN preferences.pref_value
                         ELSE preferences.pref_value::jsonb || $2::jsonb
                    END
                ),
                updated_at = NOW()
        """, self.user_id, json.dumps([brand], ensure_ascii=False), brand)

    async def add_airline(self, airline: str):
        """原子追加：用 SQL JSONB 操作避免读-写竞态。"""
        await self._ensure_user()
        await self.pool.execute("""
            INSERT INTO preferences(user_id, pref_type, pref_value)
            VALUES($1, 'airlines', $2::jsonb)
            ON CONFLICT(user_id, pref_type) DO UPDATE SET
                pref_value = (
                    CASE WHEN preferences.pref_value::jsonb ? $3
                         THEN preferences.pref_value
                         ELSE preferences.pref_value::jsonb || $2::jsonb
                    END
                ),
                updated_at = NOW()
        """, self.user_id, json.dumps([airline], ensure_ascii=False), airline)

    # ---- 聊天 ----

    async def add_chat_message(self, role: str, content: str, session_id: str = None):
        await self._ensure_user()
        await self.pool.execute("""
            INSERT INTO chat_messages(user_id, session_id, role, content)
            VALUES($1, $2, $3, $4)
        """, self.user_id, session_id, role, content)

    async def get_chat_history(self, limit: int = None, session_id: str = None) -> List[Dict]:
        await self._ensure_user()
        query = """
            SELECT role, content, created_at as timestamp, session_id
            FROM chat_messages WHERE user_id=$1
        """
        params = [self.user_id]
        if session_id:
            query += " AND session_id=$2"
            params.append(session_id)
        query += " ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = await self.pool.fetch(query, *params)
        return [{
            "role": r["role"],
            "content": r["content"],
            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            "session_id": r["session_id"],
        } for r in reversed(rows)]

    # ---- 行程 ----

    async def save_trip_history(self, trip_info: Dict[str, Any]):
        await self._ensure_user()
        # 保持与原 JSON 实现一致的业务 ID 生成规则
        existing = await self.pool.fetchval(
            "SELECT COUNT(*) FROM trip_history WHERE user_id=$1", self.user_id
        )
        trip_id = trip_info.get("trip_id") or f"trip_{existing + 1}"

        await self.pool.execute("""
            INSERT INTO trip_history(user_id, trip_id, origin, destination, start_date, end_date, purpose, extra)
            VALUES($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
        """, self.user_id, trip_id,
             trip_info.get("origin"), trip_info.get("destination"),
             trip_info.get("start_date"), trip_info.get("end_date"),
             trip_info.get("purpose"),
             json.dumps({k: v for k, v in trip_info.items()
                         if k not in ("origin", "destination", "start_date", "end_date", "purpose", "trip_id")},
                        ensure_ascii=False))

    async def get_trip_history(self, limit: int = 10) -> List[Dict]:
        await self._ensure_user()
        rows = await self.pool.fetch("""
            SELECT trip_id, origin, destination, start_date, end_date, purpose, extra, created_at as timestamp
            FROM trip_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2
        """, self.user_id, limit)
        result = []
        for r in reversed(rows):
            item = dict(r)
            item["timestamp"] = item["timestamp"].isoformat() if item["timestamp"] else None
            extra = item.pop("extra", {}) or {}
            item.update(extra)
            result.append(item)
        return result

    async def get_frequent_destinations(self, top_n: int = 5) -> List[tuple]:
        await self._ensure_user()
        rows = await self.pool.fetch("""
            SELECT destination, COUNT(*) as cnt
            FROM trip_history WHERE user_id=$1 AND destination IS NOT NULL
            GROUP BY destination ORDER BY cnt DESC LIMIT $2
        """, self.user_id, top_n)
        return [(r["destination"], r["cnt"]) for r in rows]

    # ---- 费用 ----

    async def add_expense(self, expense: Dict[str, Any]):
        await self._ensure_user()
        # 保持与原 JSON 实现一致的业务 ID 生成规则
        existing = await self.pool.fetchval(
            "SELECT COUNT(*) FROM expenses WHERE user_id=$1", self.user_id
        )
        expense_id = expense.get("id") or f"exp_{existing + 1}"

        await self.pool.execute("""
            INSERT INTO expenses(user_id, expense_id, category, amount, currency, description, expense_date)
            VALUES($1, $2, $3, $4, $5, $6, $7)
        """, self.user_id, expense_id, expense.get("category", "其他"),
             expense.get("amount", 0), expense.get("currency", "CNY"),
             expense.get("description", ""), expense.get("date"))

    async def get_expenses(self, limit: int = None) -> List[Dict]:
        await self._ensure_user()
        query = """
            SELECT expense_id as id, category, amount, currency, description,
                   expense_date as date, created_at as timestamp
            FROM expenses WHERE user_id=$1 ORDER BY created_at DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = await self.pool.fetch(query, self.user_id)
        result = []
        for r in reversed(rows):
            item = {
                "id": r["id"],
                "category": r["category"],
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "description": r["description"],
                "date": r["date"].isoformat() if r["date"] else None,
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            }
            result.append(item)
        return result

    async def delete_expense(self, index: int) -> bool:
        """删除按时间正序的第 index 条费用（与原 JSON 语义一致）。"""
        await self._ensure_user()
        row = await self.pool.fetchrow("""
            DELETE FROM expenses WHERE id = (
                SELECT id FROM expenses WHERE user_id=$1 ORDER BY created_at ASC LIMIT 1 OFFSET $2
            ) RETURNING id
        """, self.user_id, index)
        return row is not None

    async def clear_expenses(self):
        await self._ensure_user()
        await self.pool.execute("DELETE FROM expenses WHERE user_id=$1", self.user_id)

    # ---- 统计 ----

    async def increment_query_count(self):
        """原 JSON 接口兼容方法；PG 版可在 users 表增加 query_count 列，或暂由应用层维护。"""
        # 推荐方案：ALTER TABLE users ADD COLUMN query_count BIGINT DEFAULT 0;
        await self._ensure_user()
        await self.pool.execute(
            "UPDATE users SET query_count = COALESCE(query_count, 0) + 1 WHERE user_id=$1",
            self.user_id,
        )

    async def get_statistics(self) -> Dict[str, Any]:
        await self._ensure_user()
        row = await self.pool.fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM trip_history WHERE user_id=$1) as total_trips,
                (SELECT COUNT(*) FROM chat_messages WHERE user_id=$1) as total_messages,
                COALESCE(query_count, 0) as total_queries
            FROM users WHERE user_id=$1
        """, self.user_id)
        if not row:
            return {"total_trips": 0, "total_messages": 0, "total_queries": 0}
        return {
            "total_trips": row["total_trips"],
            "total_messages": row["total_messages"],
            "total_queries": row["total_queries"],
        }

    async def clear_history(self):
        """清空历史记录（保留偏好）。"""
        await self._ensure_user()
        await self.pool.execute("DELETE FROM chat_messages WHERE user_id=$1", self.user_id)
        await self.pool.execute("DELETE FROM trip_history WHERE user_id=$1", self.user_id)
        await self.pool.execute(
            "UPDATE users SET query_count = 0 WHERE user_id=$1", self.user_id
        )

    async def delete_all(self):
        """删除用户全部数据（包括偏好）。"""
        await self._ensure_user()
        await self.pool.execute("DELETE FROM users WHERE user_id=$1", self.user_id)
```

**Schema 补充（在 `users` 表增加 query_count 列以支持 `increment_query_count`）：**

```sql
ALTER TABLE users ADD COLUMN query_count BIGINT NOT NULL DEFAULT 0;
```

#### `context/memory_manager.py` — 适配层

```python
class MemoryManager:
    def __init__(self, user_id, session_id, storage_path="data/memory", llm_model=None, db_pool=None):
        self.short_term = ShortTermMemory(max_turns=10)
        if db_pool:
            self.long_term = PostgresLongTermMemory(user_id, db_pool)
        else:
            self.long_term = LongTermMemory(user_id, storage_path)

    async def add_message(self, role: str, content: str, metadata: Dict = None):
        self.short_term.add_message(role, content, metadata)
        await self.long_term.add_chat_message(role, content, self.session_id)

    async def get_full_context(self) -> Dict[str, Any]:
        return {
            "short_term": {
                "recent_dialogue": self.short_term.get_recent_context(5),
                "context_string": self.short_term.get_context_string(5),
                "statistics": self.short_term.get_statistics()
            },
            "long_term": {
                "preferences": await self.long_term.get_preference(),
                "chat_history": await self.long_term.get_chat_history(10),
                "trip_history": await self.long_term.get_trip_history(5),
                "frequent_destinations": await self.long_term.get_frequent_destinations(3),
                "statistics": await self.long_term.get_statistics()
            }
        }

    async def get_context_for_agent(self, long_term_summary: str = None) -> str:
        lines = []
        if long_term_summary:
            lines.append("【历史会话总结】")
            lines.append(long_term_summary)
            lines.append("")

        prefs = await self.long_term.get_preference()
        has_prefs = any(v for v in prefs.values() if v)
        if has_prefs:
            lines.append("【用户偏好】")
            for key, value in prefs.items():
                if value:
                    lines.append(f"- {key}: {value}")
            lines.append("")

        context_str = self.short_term.get_context_string(3)
        if context_str != "无历史对话":
            lines.append("【当前会话对话】")
            lines.append(context_str)
            lines.append("")

        return "\n".join(lines) if lines else "无上下文信息"
```

> `get_long_term_summary_async` 内部也需要把 `get_chat_history` / `get_trip_history` 改为 `await`。

#### `server/session.py` — 传入连接池，全面 async 化

```python
from db.connection import get_pool

class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, UserSession] = {}
        self._initialized = False

    async def _ensure_init(self):
        if not self._initialized:
            init_agentscope()
            self._pool = await get_pool()
            self._initialized = True

    async def get_or_create(self, user_id: str, session_id: Optional[str] = None) -> UserSession:
        await self._ensure_init()
        # ... 其余逻辑不变 ...
        memory_manager = MemoryManager(
            user_id=user_id,
            session_id=session_id,
            llm_model=model,
            db_pool=self._pool,
        )
        # ...

    async def new_session(self, user_id: str) -> UserSession:
        self._sessions = {k: v for k, v in self._sessions.items() if v.user_id != user_id}
        return await self.get_or_create(user_id)
```

#### `server/routes/chat.py` — 异步调用适配

```python
await session.memory_manager.add_message("user", request.message)
# ...
await session.memory_manager.add_message("assistant", json.dumps(result_data, ensure_ascii=False))
```

#### `server/routes/memory.py` — 所有 `long_term` 调用加 await

例如：

```python
@router.get("/api/history")
async def get_history(user_id: str = "default_user", limit: int = 10):
    session = _get_user_session(user_id)
    trips = await session.memory_manager.long_term.get_trip_history(limit=limit)
    destinations = await session.memory_manager.long_term.get_frequent_destinations(top_n=5)
    stats = await session.memory_manager.long_term.get_statistics()
    return {
        "trips": trips,
        "frequent_destinations": [{"city": c, "count": n} for c, n in destinations],
        "statistics": stats,
    }
```

其余 `/api/preferences`、`/api/context`、`/api/expenses` 同理。

#### `agents/orchestration_agent.py` — 内部同步方法 async 化

`_prepare_context` 和 `_update_memory` 都是同步方法，但调用链最终来自 async 的 `reply()`，需要改为 async：

```python
async def _prepare_context(self, intention_data: Dict[str, Any]) -> Dict[str, Any]:
    ...
    if self.memory_manager:
        preferences = await self.memory_manager.long_term.get_preference()
        context["user_preferences"] = preferences
    return context

async def _update_memory(self, intention_data: Dict[str, Any], results: List[Dict]):
    ...
    current_prefs = await self.memory_manager.long_term.get_preference()
    ...
    await self.memory_manager.long_term.save_preference(pref_type, existing_value)
    ...
    await self.memory_manager.long_term.save_trip_history({...})
```

并在 `reply()` 中改为：

```python
context = await self._prepare_context(intention_data)
# ...
await self._update_memory(intention_data, results)
```

#### `.claude/skills/expense-tracker/script/agent.py` — 同步执行链 async 化

`_execute_action`、`_record_expense`、`_query_expenses`、`_delete_expense` 当前都是同步方法。由于它们会调用 `long_term.add_expense` / `delete_expense`，需要全部改为 async：

```python
async def _execute_action(self, parsed: dict, existing: list) -> dict:
    ...

async def _record_expense(self, parsed: dict, existing: list) -> dict:
    ...
    await self.memory_manager.long_term.add_expense(expense)
    ...

async def _delete_expense(self, parsed: dict, existing: list) -> dict:
    ...
    await self.memory_manager.long_term.delete_expense(idx)
    ...
```

然后在 `reply()` 中：`result = await self._execute_action(result, existing_expenses)`。

#### `.claude/skills/preference/script/agent.py`

```python
current_preferences = await self.memory_manager.long_term.get_preference()
```

#### `.claude/skills/memory-query/script/agent.py`

```python
trip_history = await self.memory_manager.long_term.get_trip_history(limit=50)
preferences = await self.memory_manager.long_term.get_preference()
```

#### `server/app.py` — 生命周期管理

使用 FastAPI 的 `lifespan` 管理连接池：

```python
from contextlib import asynccontextmanager
from db.connection import close_pool, get_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()

app = FastAPI(lifespan=lifespan)
```

#### `cli.py`

CLI 当前直接同步创建 `MemoryManager`。若要支持 PostgreSQL，需要：
1. 在 `initialize_system()` 中 `await get_pool()` 获取 pool。
2. 把 `MemoryManager(..., db_pool=pool)` 传入。
3. 所有调用 `long_term.xxx()` 的命令（如 `status`、`history`、`preferences`）都要 `await`。
4. `get_full_context()` 在 CLI 中需要 `await`。

#### `config.py`

```python
DATABASE_URL = os.environ.get("ALIGO_DATABASE_URL", "")
```

- 空字符串：走原 JSON 文件模式（开发环境无需安装 PostgreSQL）。
- 非空且格式正确：走 PostgreSQL 模式。

---

## 五、兼容与回退策略

### 环境变量切换

```bash
# 使用 PostgreSQL
ALIGO_DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<db>

# 不设置 ALIGO_DATABASE_URL 或为空字符串 → 回退到 JSON 文件模式
```

### 数据库不可用时的策略

- 开发/测试环境：未配置 `ALIGO_DATABASE_URL` 时自动回退 JSON。
- 生产环境：配置了 `ALIGO_DATABASE_URL` 但连接失败时**直接报错**，不静默回退，避免双写导致数据混乱。

---

## 六、数据迁移

### `db/migrate.py`

一次性脚本，将现有 JSON 文件导入 PostgreSQL。建议运行前备份 `data/memory/`。

```python
"""JSON → PostgreSQL 数据迁移"""
import asyncio
import json
from pathlib import Path
from db.connection import get_pool

MEMORY_DIR = Path("data/memory")


async def migrate():
    pool = await get_pool()
    if pool is None:
        print("ALIGO_DATABASE_URL not set, nothing to migrate.")
        return

    for json_file in MEMORY_DIR.glob("*.json"):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        user_id = data.get("user_id", json_file.stem)
        print(f"Migrating user: {user_id}")

        await pool.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id)

        for pref in data.get("preferences", []):
            await pool.execute("""
                INSERT INTO preferences(user_id, pref_type, pref_value)
                VALUES($1, $2, $3::jsonb)
                ON CONFLICT(user_id, pref_type) DO UPDATE SET pref_value=$3::jsonb
            """, user_id, pref["type"], json.dumps(pref["value"], ensure_ascii=False))

        for msg in data.get("chat_history", []):
            ts = msg.get("timestamp")
            await pool.execute("""
                INSERT INTO chat_messages(user_id, session_id, role, content, created_at)
                VALUES($1, $2, $3, $4, $5)
            """, user_id, msg.get("session_id"), msg["role"], msg["content"], ts)

        for trip in data.get("trip_history", []):
            extra = {k: v for k, v in trip.items()
                     if k not in ("trip_id", "origin", "destination", "start_date", "end_date", "purpose", "timestamp")}
            await pool.execute("""
                INSERT INTO trip_history(user_id, trip_id, origin, destination, start_date, end_date, purpose, extra, created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)
            """, user_id, trip.get("trip_id", ""), trip.get("origin"), trip.get("destination"),
                 trip.get("start_date"), trip.get("end_date"), trip.get("purpose"),
                 json.dumps(extra, ensure_ascii=False), trip.get("timestamp"))

        for exp in data.get("expenses", []):
            await pool.execute("""
                INSERT INTO expenses(user_id, expense_id, category, amount, currency, description, expense_date, created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)
            """, user_id, exp.get("id", ""), exp.get("category", "其他"), exp.get("amount", 0),
                 exp.get("currency", "CNY"), exp.get("description", ""), exp.get("date"), exp.get("timestamp"))

        # 迁移 query_count
        total_queries = data.get("statistics", {}).get("total_queries", 0)
        await pool.execute(
            "UPDATE users SET query_count=$1 WHERE user_id=$2", total_queries, user_id
        )

        print(f"  Done: {len(data.get('chat_history', []))} msgs, {len(data.get('expenses', []))} expenses")


if __name__ == "__main__":
    asyncio.run(migrate())
```

> 该脚本设计为**一次性运行**。重复运行会导致 `chat_messages/trip_history/expenses` 重复插入。生产迁移前请备份，并在迁移后校验数据一致性。

---

## 七、依赖变更

### `requirements.txt` 新增

```
asyncpg>=0.29.0
```

### Docker（可选）

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: aligo
      POSTGRES_USER: aligo
      POSTGRES_PASSWORD: aligo
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql
volumes:
  pgdata:
```

---

## 八、改造影响范围汇总

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `config.py` | 小改 | 新增 `DATABASE_URL` |
| `db/connection.py` | **新增** | asyncpg 连接池，带初始化锁 |
| `db/schema.sql` | **新增** | DDL，含 users、preferences、chat_messages、trip_history、expenses、plugin_config 六张表 |
| `db/migrate.py` | **新增** | JSON → PG 迁移脚本（含 plugin_config） |
| `agents/lazy_agent_registry.py` | 中改 | 插件配置读写支持 PG 模式 |
| `context/long_term_memory.py` | **新增类** | `PostgresLongTermMemory`，补齐所有方法 |
| `context/memory_manager.py` | 中改 | `add_message` 改 async；`get_full_context`/`get_context_for_agent` 改 async |
| `server/session.py` | 中改 | `_ensure_init`/`get_or_create`/`new_session` 改 async |
| `server/app.py` | 中改 | 使用 `lifespan` 管理连接池 |
| `server/routes/chat.py` | 小改 | 两处 `add_message` 加 `await` |
| `server/routes/memory.py` | 中改 | 所有 `long_term.xxx()` 加 `await` |
| `agents/orchestration_agent.py` | 中改 | `_prepare_context`、`_update_memory` 及内部调用改 async |
| `.claude/skills/expense-tracker/script/agent.py` | 中改 | `_execute_action` 及子方法改 async |
| `.claude/skills/preference/script/agent.py` | 小改 | `get_preference` 加 `await` |
| `.claude/skills/memory-query/script/agent.py` | 小改 | `get_trip_history`/`get_preference` 加 `await` |
| `cli.py` | 中改 | 异步初始化 MemoryManager，所有 long_term 调用加 await |
| `requirements.txt` | 小改 | 新增 `asyncpg` |
| `tests/test_memory_system.py` | 小改 | 明确使用 JSON 模式测试，或提供测试 PG 实例 |
| `agents/intention_agent.py` | **不动** | 通过 memory_manager 间接访问 |
| `.claude/skills/query-info/script/agent.py` | **不动** | 不访问长期记忆 |
| `.claude/skills/plan-trip/script/agent.py` | **不动** | 从 context 接收偏好，不直接访问长期记忆 |
| `web/` | **不动** | 前端不感知存储层变化 |

---

## 九、实施步骤

1. **环境准备**：启动 PostgreSQL，执行 `db/schema.sql` 建库建表（含 `query_count` 列）。
2. **新增 `db/connection.py`**：连接池 + 初始化锁。
3. **新增 `PostgresLongTermMemory`**：在 `long_term_memory.py` 中追加，保持与原类方法一致且为 async。
4. **改造 `MemoryManager`**：`add_message`/`get_full_context`/`get_context_for_agent` 改 async。
5. **改造 `SessionManager`**：`_ensure_init`/`get_or_create`/`new_session` 改 async，传入 pool。
6. **改造 `server/app.py`**：使用 `lifespan` 初始化/关闭连接池。
7. **改造 `chat.py`**：两处 `add_message` 加 `await`。
8. **改造 `server/routes/memory.py`**：所有 `long_term` 调用加 `await`。
9. **改造 `agents/orchestration_agent.py`**：`_prepare_context`、`_update_memory` 及内部调用改 async。
10. **改造 Skill Agent**：expense-tracker、preference、memory-query 中的同步调用改 async。
11. **改造 `cli.py`**：异步初始化，await 所有长期记忆调用。
12. **改造 `config.py`**：新增 `DATABASE_URL`。
13. **运行迁移脚本**：`python -m db.migrate`。
14. **测试**：
    - `pytest`
    - `python tests/test_cli_qa.py`
    - 手动验证所有 Skill（偏好、费用、行程、记忆查询）。
15. **清理（可选）**：确认稳定后，移除 JSON 文件模式的回退代码。

---

## 十、风险与注意事项

1. **异步化范围是最大风险**：初版设计低估了把同步 JSON 接口改为异步数据库接口的影响面。实际需改动 `server/routes`、`agents/orchestration_agent.py`、多个 Skill Agent 和 CLI。
2. **行为一致性**：`delete_expense`、`save_trip_history`、`add_expense` 的业务 ID 生成规则必须与原 JSON 实现保持一致，否则测试和前端会失效。
3. **时间字段兼容**：数据库返回 `datetime` 对象，API 输出应统一转换为 ISO 字符串，保持与原 JSON 返回值一致。
4. **迁移幂等性**：迁移脚本为一次性脚本，重复运行会产生重复数据。生产环境迁移前务必备份。
5. **回退策略**：未配置 `ALIGO_DATABASE_URL` 时回退 JSON；配置后数据库连不上时建议直接报错，不静默回退。

---

## 十一、plugin_config 迁移

### 11.1 当前存储

`data/plugin_config.json` 存储每个插件的启用/禁用状态，由 `LazyAgentRegistry` 管理。当前结构为全局配置（不区分用户），但迁移到数据库后可扩展为按用户配置。

### 11.2 改造方案

**`agents/lazy_agent_registry.py`** 新增 PG 支持：

```python
class LazyAgentRegistry:
    def __init__(self, model, cache, memory_manager, db_pool=None):
        self._pool = db_pool
        # ...

    async def _load_config(self) -> Dict:
        if self._pool:
            rows = await self._pool.fetch(
                "SELECT plugin_name, enabled FROM plugin_config WHERE user_id=$1",
                self._user_id,
            )
            return {r["plugin_name"]: {"enabled": r["enabled"]} for r in rows}
        # 回退：读 JSON 文件
        return self._load_config_json()

    async def set_plugin_enabled(self, skill_name: str, enabled: bool):
        if self._pool:
            await self._pool.execute("""
                INSERT INTO plugin_config(user_id, plugin_name, enabled)
                VALUES($1, $2, $3)
                ON CONFLICT(user_id, plugin_name)
                DO UPDATE SET enabled=$3, updated_at=NOW()
            """, self._user_id, skill_name, enabled)
        else:
            self._config[skill_name] = {"enabled": enabled}
            self._save_config_json()
```

### 11.3 迁移脚本补充

在 `db/migrate.py` 中追加：

```python
# 迁移 plugin_config（写入 default_user）
config_path = Path("data/plugin_config.json")
if config_path.exists():
    with open(config_path, "r", encoding="utf-8") as f:
        plugins = json.load(f)
    for name, cfg in plugins.items():
        await pool.execute("""
            INSERT INTO plugin_config(user_id, plugin_name, enabled)
            VALUES('default_user', $1, $2)
            ON CONFLICT(user_id, plugin_name) DO UPDATE SET enabled=$2
        """, name, cfg.get("enabled", True))
    print(f"  Migrated {len(plugins)} plugin configs")
```

---

## 十二、测试策略

### 12.1 测试分层

| 层级 | 工具 | 说明 |
|------|------|------|
| 单元测试 | `pytest` + 内存 SQLite 或 `asyncpg` 测试容器 | `PostgresLongTermMemory` 各方法的输入输出 |
| 集成测试 | `pytest` + `testcontainers-python` | 启动真实 PG 容器，跑完整 CRUD + 事务 |
| 端到端 | `python tests/test_cli_qa.py` | CLI + Web 全链路，验证 API 返回值不变 |
| 回归对比 | 自定义脚本 | 同一输入分别走 JSON 和 PG，diff 返回值 |

### 12.2 测试 Fixture

```python
# tests/conftest.py
import pytest
import asyncpg

@pytest.fixture(scope="session")
async def pg_pool():
    """启动测试用连接池（需要本地 PG 或 testcontainers）。"""
    pool = await asyncpg.create_pool(
        dsn="postgresql://<user>:<password>@localhost:5432/<db>_test",
        min_size=1, max_size=3,
    )
    # 执行 schema
    with open("db/schema.sql") as f:
        await pool.execute(f.read())
    yield pool
    await pool.close()

@pytest.fixture
async def memory(pg_pool):
    """每个测试用例独立的 LongTermMemory 实例，测试后清理数据。"""
    from context.long_term_memory import PostgresLongTermMemory
    mem = PostgresLongTermMemory("test_user", pg_pool)
    yield mem
    await pg_pool.execute("DELETE FROM users WHERE user_id='test_user'")
```

### 12.3 关键测试用例

```
test_save_and_get_preference          # 单值偏好 CRUD
test_add_hotel_brand_concurrent       # 并发追加不丢失（验证竞态修复）
test_chat_history_session_filter      # 按 session_id 过滤
test_trip_history_ordering            # 时间倒序 + limit
test_delete_expense_by_index          # 索引删除语义一致
test_get_statistics_realtime          # COUNT 实时计算
test_cascade_delete_user              # 删除用户级联清理所有子表
test_json_fallback                    # 未配置 DATABASE_URL 时走 JSON
test_migration_script                 # JSON 导入后数据完整性
```

---

## 十三、运维手册

### 13.1 备份策略

```bash
# 每日全量备份（crontab）
0 3 * * * pg_dump -U aligo -d aligo -F c -f /backup/aligo_$(date +\%Y\%m\%d).dump

# 保留最近 7 天
find /backup -name "aligo_*.dump" -mtime +7 -delete

# 恢复
pg_restore -U aligo -d aligo /backup/aligo_20260728.dump
```

### 13.2 监控指标

| 指标 | 查询 | 告警阈值 |
|------|------|---------|
| 连接池使用率 | `SELECT count(*) FROM pg_stat_activity WHERE datname='aligo'` | > 8（max_size=10） |
| 表膨胀 | `SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname='chat_messages'` | > 10000 |
| 慢查询 | `pg_stat_statements` 中 `mean_time > 500ms` | 持续出现 |
| 磁盘占用 | `pg_database_size('aligo')` | > 1GB |

```sql
-- 常用诊断 SQL
-- 查看各表行数
SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;

-- 查看索引使用率
SELECT indexrelname, idx_scan, idx_tup_read FROM pg_stat_user_indexes;

-- 查看锁等待
SELECT * FROM pg_locks WHERE NOT granted;
```

### 13.3 连接池调优

```python
# db/connection.py 中的连接池参数
_pool = await asyncpg.create_pool(
    dsn=DATABASE_URL,
    min_size=2,        # 最小空闲连接（CLI 场景可设为 1）
    max_size=10,       # 最大连接数（单实例，与 uvicorn workers 数匹配）
    max_inactive_connection_lifetime=300,  # 空闲连接 5 分钟回收
    command_timeout=30, # 单条 SQL 超时 30 秒
)
```

**多实例部署时**：每个 uvicorn worker 进程独立持有连接池。若 `workers=4`，总连接数上限 = `4 × max_size`。需确保 PostgreSQL 的 `max_connections`（默认 100）留有余量。

### 13.4 灾难恢复

| 场景 | 恢复方案 |
|------|---------|
| PG 宕机 | 设置 `ALIGO_DATABASE_URL=""` 回退 JSON 模式，业务不中断 |
| 数据损坏 | 从 `pg_dump` 备份恢复，运行 `db/migrate.py` 补增量 |
| 迁移失败 | 删除新建表，回退 JSON 模式，排查后重跑迁移脚本 |

---

## 十四、性能考量

### 14.1 预期查询模式与索引覆盖

| 查询 | 索引 | 扫描方式 |
|------|------|---------|
| `get_preference(user_id)` | `idx_preferences_user` | Index Scan |
| `get_chat_history(user_id, limit)` | `idx_chat_user_time` | Index Scan DESC + Limit |
| `get_trip_history(user_id, limit)` | `idx_trip_user` | Index Scan DESC + Limit |
| `get_expenses(user_id, category)` | `idx_expense_user_cat` | Index Scan |
| `get_frequent_destinations(user_id)` | `idx_trip_dest` | Index Scan + GroupAggregate |

### 14.2 数据增长估算

假设日活 100 用户，每用户日均 20 条消息：

| 表 | 日增量 | 年增量 | 单行大小 | 年数据量 |
|----|--------|--------|---------|---------|
| `chat_messages` | 2,000 | ~73 万 | ~500B | ~350MB |
| `trip_history` | 50 | ~1.8 万 | ~200B | ~3.5MB |
| `expenses` | 200 | ~7.3 万 | ~150B | ~1MB |

chat_messages 是主要增长点。一年 73 万行对 PostgreSQL 毫无压力。若未来增长 10 倍，可考虑按 `created_at` 做**范围分区**：

```sql
-- 未来优化：chat_messages 按月分区
CREATE TABLE chat_messages (
    -- ...
) PARTITION BY RANGE (created_at);

CREATE TABLE chat_messages_2026_07 PARTITION OF chat_messages
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
```

### 14.3 pgvector 替代 Milvus Lite（可选）

若希望统一数据库，可用 `pgvector` 扩展替代 Milvus Lite，将 RAG 向量检索也纳入 PostgreSQL：

```sql
CREATE EXTENSION vector;

CREATE TABLE knowledge_vectors (
    id          BIGSERIAL PRIMARY KEY,
    collection  VARCHAR(64) NOT NULL,     -- business_travel_knowledge / visa_knowledge
    content     TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    embedding   vector(512) NOT NULL      -- bge-small-zh-v1.5 维度
);
CREATE INDEX idx_vector_embedding ON knowledge_vectors
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

**权衡**：pgvector 适合数据量 < 100 万条的场景；Milvus Lite 在大规模向量检索上性能更优。当前项目数据量小，两者均可。建议先完成结构化数据迁移，pgvector 作为后续优化。

---

## 十五、版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-27 | 初版设计 |
| v2.0 | 2026-07-28 | 修订：明确异步化影响范围，补充所有代码改造示例 |
| v2.1 | 2026-07-28 | 新增 ER 图、plugin_config 迁移、测试策略、运维手册、性能考量；修复 add_hotel_brand/add_airline 并发竞态 |
