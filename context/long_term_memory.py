"""
长期记忆 (Long-term Memory)
持久化存储用户信息，支持跨会话访问

提供两种实现：
- LongTermMemory: JSON 文件存储（同步，开发/回退用）
- PostgresLongTermMemory: PostgreSQL 存储（异步，生产用）
"""
from typing import Dict, Any, List, Optional
import json
import os
import atexit
from datetime import datetime, date as _date
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    长期记忆：持久化用户信息
    - 用户偏好（家庭地址、酒店品牌、航空公司等）
    - 历史行程记录
    - 统计信息
    - 写回缓存：内存读写，定期/退出时 flush 到文件
    """

    def __init__(self, user_id: str, storage_path: str = "data/memory"):
        self.user_id = user_id
        self.storage_path = storage_path
        self.db_path = os.path.join(storage_path, f"{user_id}.json")
        self._dirty = False

        Path(storage_path).mkdir(parents=True, exist_ok=True)
        self.data = self._load()

        # 进程退出时自动 flush
        atexit.register(self.flush)
        logger.info(f"Long-term memory initialized for user: {user_id}")

    def _load(self) -> Dict[str, Any]:
        """从文件加载数据"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.debug(f"Loaded long-term memory from {self.db_path}")

                    # 数据迁移：兼容旧格式
                    data = self._migrate_data(data)
                    return data
            except Exception as e:
                logger.error(f"Failed to load long-term memory: {e}")
                return self._init_data()
        else:
            logger.info("No existing long-term memory, creating new")
            return self._init_data()

    def _migrate_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        迁移旧数据格式到新格式

        Args:
            data: 原始数据

        Returns:
            迁移后的数据
        """
        # 1. 确保必需字段存在
        if "chat_history" not in data:
            data["chat_history"] = []
        if "trip_history" not in data:
            data["trip_history"] = []
        if "statistics" not in data:
            data["statistics"] = {}
        if "total_messages" not in data.get("statistics", {}):
            data["statistics"]["total_messages"] = 0
        if "total_queries" not in data.get("statistics", {}):
            data["statistics"]["total_queries"] = 0
        if "preferences" not in data:
            data["preferences"] = []
        if "expenses" not in data:
            data["expenses"] = []

        # 2. 迁移旧格式：字典 → 列表
        if isinstance(data.get("preferences"), dict):
            old_prefs = data["preferences"]
            new_prefs = []
            for pref_type, pref_value in old_prefs.items():
                if pref_value is not None:
                    new_prefs.append({"type": pref_type, "value": pref_value})
            data["preferences"] = new_prefs
            logger.info(f"Migrated: Converted preferences from dict to list ({len(new_prefs)} items)")

        # 3. 修复嵌套 bug（旧代码产生的错误数据）
        if isinstance(data.get("preferences"), list):
            fixed_prefs = []
            for pref in data["preferences"]:
                if isinstance(pref, dict):
                    # 错误的嵌套：{"type": "preferences", "value": [...]}
                    if pref.get("type") == "preferences" and isinstance(pref.get("value"), list):
                        for nested_pref in pref["value"]:
                            if isinstance(nested_pref, dict) and "type" in nested_pref:
                                fixed_prefs.append({"type": nested_pref["type"], "value": nested_pref["value"]})
                        logger.info("Migrated: Fixed nested preferences bug")
                    else:
                        fixed_prefs.append(pref)

            if fixed_prefs != data["preferences"]:
                data["preferences"] = fixed_prefs

        # 保存迁移后的数据
        self.data = data
        self._save()

        return data

    def _init_data(self) -> Dict[str, Any]:
        """初始化数据结构"""
        return {
            "user_id": self.user_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "preferences": [],  # 偏好列表: [{"type": "home_location", "value": "天津"}, ...]
            "chat_history": [],  # 所有聊天记录（跨会话）
            "trip_history": [],  # 所有行程记录
            "expenses": [],  # 费用记录
            "statistics": {
                "total_trips": 0,
                "total_messages": 0,
                "total_queries": 0,
                "frequent_destinations": {}
            }
        }

    def _save(self):
        """保存数据到文件"""
        try:
            self.data["updated_at"] = datetime.now().isoformat()
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            self._dirty = False
            logger.debug(f"Saved long-term memory to {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to save long-term memory: {e}")

    def flush(self):
        """手动 flush 脏数据到文件（进程退出时自动调用）"""
        if self._dirty:
            self._save()
            logger.debug(f"Flushed long-term memory for user: {self.user_id}")

    def save_preference(self, pref_type: str, value: Any):
        """
        保存用户偏好（列表格式）

        Args:
            pref_type: 偏好类型
            value: 偏好值
        """
        # 查找是否已存在该类型的偏好
        preferences = self.data["preferences"]
        found = False

        for pref in preferences:
            if pref.get("type") == pref_type:
                pref["value"] = value
                found = True
                break

        # 如果不存在，添加新的偏好
        if not found:
            preferences.append({"type": pref_type, "value": value})

        self._save()
        logger.info(f"Saved preference: {pref_type} = {value}")

    def get_preference(self, pref_type: str = None) -> Any:
        """
        获取用户偏好

        Args:
            pref_type: 偏好类型，None返回字典格式的全部偏好

        Returns:
            偏好值或偏好字典
        """
        preferences = self.data["preferences"]

        if pref_type is None:
            # 返回字典格式，方便调用方使用
            result = {}
            for pref in preferences:
                result[pref.get("type")] = pref.get("value")
            return result
        else:
            # 查找特定类型的偏好
            for pref in preferences:
                if pref.get("type") == pref_type:
                    return pref.get("value")
            return None

    def add_hotel_brand(self, brand: str):
        """添加酒店品牌偏好（追加到列表）"""
        # 查找 hotel_brands 偏好
        preferences = self.data["preferences"]
        found = False

        for pref in preferences:
            if pref.get("type") == "hotel_brands":
                # 确保 value 是列表
                if not isinstance(pref["value"], list):
                    pref["value"] = [pref["value"]] if pref["value"] else []

                # 追加品牌
                if brand not in pref["value"]:
                    pref["value"].append(brand)
                found = True
                break

        # 如果不存在，创建新的
        if not found:
            preferences.append({"type": "hotel_brands", "value": [brand]})

        self._save()
        logger.info(f"Added hotel brand preference: {brand}")

    def add_airline(self, airline: str):
        """添加航空公司偏好（追加到列表）"""
        # 查找 airlines 偏好
        preferences = self.data["preferences"]
        found = False

        for pref in preferences:
            if pref.get("type") == "airlines":
                # 确保 value 是列表
                if not isinstance(pref["value"], list):
                    pref["value"] = [pref["value"]] if pref["value"] else []

                # 追加航空公司
                if airline not in pref["value"]:
                    pref["value"].append(airline)
                found = True
                break

        # 如果不存在，创建新的
        if not found:
            preferences.append({"type": "airlines", "value": [airline]})

        self._save()
        logger.info(f"Added airline preference: {airline}")

    def add_chat_message(self, role: str, content: str, session_id: str = None):
        """
        添加聊天消息到长期记忆

        Args:
            role: 角色 (user/assistant)
            content: 消息内容
            session_id: 会话ID（可选）
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id
        }

        self.data["chat_history"].append(message)
        self.data["statistics"]["total_messages"] += 1
        self._save()
        logger.debug(f"Added chat message to long-term memory: {role}")

    def get_chat_history(self, limit: int = None, session_id: str = None) -> List[Dict[str, Any]]:
        """
        获取聊天历史

        Args:
            limit: 返回数量限制
            session_id: 会话ID（只返回特定会话的消息）

        Returns:
            消息列表
        """
        messages = self.data["chat_history"]

        if session_id:
            messages = [m for m in messages if m.get("session_id") == session_id]

        if limit:
            return messages[-limit:]
        return messages

    def save_trip_history(self, trip_info: Dict[str, Any]):
        """
        保存行程历史

        Args:
            trip_info: 行程信息
        """
        trip_record = {
            "trip_id": f"trip_{len(self.data['trip_history']) + 1}",
            "timestamp": datetime.now().isoformat(),
            **trip_info
        }

        self.data["trip_history"].append(trip_record)

        # 更新统计信息
        self.data["statistics"]["total_trips"] += 1

        # 更新常去目的地统计
        destination = trip_info.get("destination")
        if destination:
            freq = self.data["statistics"]["frequent_destinations"]
            freq[destination] = freq.get(destination, 0) + 1

        self._save()
        logger.info(f"Saved trip history: {trip_record['trip_id']}")

    def get_trip_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取历史行程

        Args:
            limit: 返回数量限制

        Returns:
            行程列表
        """
        return self.data["trip_history"][-limit:] if limit else self.data["trip_history"]

    def get_frequent_destinations(self, top_n: int = 5) -> List[tuple]:
        """
        获取常去目的地

        Args:
            top_n: 返回前N个

        Returns:
            [(destination, count), ...]
        """
        freq = self.data["statistics"]["frequent_destinations"]
        sorted_dest = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return sorted_dest[:top_n]

    def increment_query_count(self):
        """增加查询计数"""
        self.data["statistics"]["total_queries"] += 1
        self._save()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.data["statistics"].copy()

    def clear_history(self):
        """清空历史记录（保留偏好）"""
        self.data["chat_history"] = []
        self.data["trip_history"] = []
        self.data["statistics"]["total_trips"] = 0
        self.data["statistics"]["total_messages"] = 0
        self.data["statistics"]["frequent_destinations"] = {}
        self._save()
        logger.info("Cleared all history (chat + trips)")

    def delete_all(self):
        """删除所有数据（包括文件）"""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            logger.warning(f"Deleted long-term memory file: {self.db_path}")

    # ---- 费用记录 ----

    def add_expense(self, expense: Dict[str, Any]):
        """添加一笔费用记录"""
        expense.setdefault("id", f"exp_{len(self.data['expenses']) + 1}")
        expense.setdefault("timestamp", datetime.now().isoformat())
        self.data["expenses"].append(expense)
        self._save()
        logger.info(f"Added expense: {expense.get('category')} {expense.get('amount')}")

    def get_expenses(self, limit: int = None) -> List[Dict[str, Any]]:
        """获取费用记录"""
        expenses = self.data.get("expenses", [])
        return expenses[-limit:] if limit else expenses

    def delete_expense(self, index: int) -> bool:
        """删除指定索引的费用记录"""
        expenses = self.data.get("expenses", [])
        if 0 <= index < len(expenses):
            expenses.pop(index)
            self._save()
            return True
        return False

    def clear_expenses(self):
        """清空所有费用记录"""
        self.data["expenses"] = []
        self._save()
        logger.info("Cleared all expenses")


def _to_date(s):
    """将日期字符串转为 datetime.date，无效值返回 None"""
    if not s:
        return None
    if isinstance(s, _date):
        return s
    try:
        return _date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


class PostgresLongTermMemory:
    """基于 PostgreSQL 的长期记忆实现（异步接口）。"""

    def __init__(self, user_id: str, pool):
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
        await self.pool.execute(
            """
            INSERT INTO preferences(user_id, pref_type, pref_value)
            VALUES($1, $2, $3)
            ON CONFLICT(user_id, pref_type)
            DO UPDATE SET pref_value = $3, updated_at = NOW()
            """,
            self.user_id,
            pref_type,
            value,
        )

    async def get_preference(self, pref_type: str = None) -> Any:
        await self._ensure_user()
        if pref_type:
            row = await self.pool.fetchrow(
                "SELECT pref_value FROM preferences WHERE user_id=$1 AND pref_type=$2",
                self.user_id,
                pref_type,
            )
            return row["pref_value"] if row else None
        else:
            rows = await self.pool.fetch(
                "SELECT pref_type, pref_value FROM preferences WHERE user_id=$1",
                self.user_id,
            )
            return {r["pref_type"]: r["pref_value"] for r in rows}

    async def add_hotel_brand(self, brand: str):
        """原子追加酒店品牌。"""
        await self._ensure_user()
        await self.pool.execute(
            """
            INSERT INTO preferences(user_id, pref_type, pref_value)
            VALUES($1, 'hotel_brands', $2)
            ON CONFLICT(user_id, pref_type) DO UPDATE SET
                pref_value = (
                    CASE WHEN preferences.pref_value ? $3
                         THEN preferences.pref_value
                         ELSE preferences.pref_value || $2
                    END
                ),
                updated_at = NOW()
            """,
            self.user_id,
            [brand],
            brand,
        )

    async def add_airline(self, airline: str):
        """原子追加航空公司。"""
        await self._ensure_user()
        await self.pool.execute(
            """
            INSERT INTO preferences(user_id, pref_type, pref_value)
            VALUES($1, 'airlines', $2)
            ON CONFLICT(user_id, pref_type) DO UPDATE SET
                pref_value = (
                    CASE WHEN preferences.pref_value ? $3
                         THEN preferences.pref_value
                         ELSE preferences.pref_value || $2
                    END
                ),
                updated_at = NOW()
            """,
            self.user_id,
            [airline],
            airline,
        )

    # ---- 聊天 ----

    async def add_chat_message(self, role: str, content: str, session_id: str = None):
        await self._ensure_user()
        await self.pool.execute(
            """
            INSERT INTO chat_messages(user_id, session_id, role, content)
            VALUES($1, $2, $3, $4)
            """,
            self.user_id,
            session_id,
            role,
            content,
        )

    async def get_chat_history(self, limit: int = None, session_id: str = None) -> List[Dict]:
        await self._ensure_user()
        query = "SELECT role, content, created_at as timestamp, session_id FROM chat_messages WHERE user_id=$1"
        params: list = [self.user_id]
        if session_id:
            query += " AND session_id=$2"
            params.append(session_id)
        query += " ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = await self.pool.fetch(query, *params)
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                "session_id": r["session_id"],
            }
            for r in reversed(rows)
        ]

    # ---- 行程 ----

    async def save_trip_history(self, trip_info: Dict[str, Any]):
        await self._ensure_user()
        existing = await self.pool.fetchval(
            "SELECT COUNT(*) FROM trip_history WHERE user_id=$1", self.user_id
        )
        trip_id = trip_info.get("trip_id") or f"trip_{existing + 1}"

        extra = {
            k: v
            for k, v in trip_info.items()
            if k not in ("origin", "destination", "start_date", "end_date", "purpose", "trip_id")
        }
        await self.pool.execute(
            """
            INSERT INTO trip_history(user_id, trip_id, origin, destination, start_date, end_date, purpose, extra)
            VALUES($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            self.user_id,
            trip_id,
            trip_info.get("origin"),
            trip_info.get("destination"),
            _to_date(trip_info.get("start_date")),
            _to_date(trip_info.get("end_date")),
            trip_info.get("purpose"),
            extra,
        )

    async def get_trip_history(self, limit: int = 10) -> List[Dict]:
        await self._ensure_user()
        rows = await self.pool.fetch(
            """
            SELECT trip_id, origin, destination, start_date, end_date, purpose, extra, created_at as timestamp
            FROM trip_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2
            """,
            self.user_id,
            limit,
        )
        result = []
        for r in reversed(rows):
            item = dict(r)
            item["timestamp"] = item["timestamp"].isoformat() if item["timestamp"] else None
            item["start_date"] = item["start_date"].isoformat() if item.get("start_date") else None
            item["end_date"] = item["end_date"].isoformat() if item.get("end_date") else None
            extra = item.pop("extra", {}) or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except (json.JSONDecodeError, TypeError):
                    extra = {}
            item.update(extra)
            result.append(item)
        return result

    async def get_frequent_destinations(self, top_n: int = 5) -> List[tuple]:
        await self._ensure_user()
        rows = await self.pool.fetch(
            """
            SELECT destination, COUNT(*) as cnt
            FROM trip_history WHERE user_id=$1 AND destination IS NOT NULL
            GROUP BY destination ORDER BY cnt DESC LIMIT $2
            """,
            self.user_id,
            top_n,
        )
        return [(r["destination"], r["cnt"]) for r in rows]

    # ---- 费用 ----

    async def add_expense(self, expense: Dict[str, Any]):
        await self._ensure_user()
        existing = await self.pool.fetchval(
            "SELECT COUNT(*) FROM expenses WHERE user_id=$1", self.user_id
        )
        expense_id = expense.get("id") or f"exp_{existing + 1}"

        await self.pool.execute(
            """
            INSERT INTO expenses(user_id, expense_id, category, amount, currency, description, expense_date)
            VALUES($1, $2, $3, $4, $5, $6, $7)
            """,
            self.user_id,
            expense_id,
            expense.get("category", "其他"),
            expense.get("amount", 0),
            expense.get("currency", "CNY"),
            expense.get("description", ""),
            _to_date(expense.get("date")),
        )

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
        return [
            {
                "id": r["id"],
                "category": r["category"],
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "description": r["description"],
                "date": r["date"].isoformat() if r["date"] else None,
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            }
            for r in reversed(rows)
        ]

    async def delete_expense(self, index: int) -> bool:
        """删除按时间正序的第 index 条费用（与原 JSON 语义一致）。"""
        await self._ensure_user()
        row = await self.pool.fetchrow(
            """
            DELETE FROM expenses WHERE id = (
                SELECT id FROM expenses WHERE user_id=$1 ORDER BY created_at ASC LIMIT 1 OFFSET $2
            ) RETURNING id
            """,
            self.user_id,
            index,
        )
        return row is not None

    async def clear_expenses(self):
        await self._ensure_user()
        await self.pool.execute("DELETE FROM expenses WHERE user_id=$1", self.user_id)

    # ---- 统计 ----

    async def increment_query_count(self):
        await self._ensure_user()
        await self.pool.execute(
            "UPDATE users SET query_count = COALESCE(query_count, 0) + 1 WHERE user_id=$1",
            self.user_id,
        )

    async def get_statistics(self) -> Dict[str, Any]:
        await self._ensure_user()
        row = await self.pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM trip_history WHERE user_id=$1) as total_trips,
                (SELECT COUNT(*) FROM chat_messages WHERE user_id=$1) as total_messages,
                COALESCE(query_count, 0) as total_queries
            FROM users WHERE user_id=$1
            """,
            self.user_id,
        )
        if not row:
            return {"total_trips": 0, "total_messages": 0, "total_queries": 0, "frequent_destinations": {}}
        # frequent_destinations 实时计算
        freq_rows = await self.pool.fetch(
            """
            SELECT destination, COUNT(*) as cnt
            FROM trip_history WHERE user_id=$1 AND destination IS NOT NULL
            GROUP BY destination ORDER BY cnt DESC LIMIT 10
            """,
            self.user_id,
        )
        return {
            "total_trips": row["total_trips"],
            "total_messages": row["total_messages"],
            "total_queries": row["total_queries"],
            "frequent_destinations": {r["destination"]: r["cnt"] for r in freq_rows},
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
        self._user_ensured = False
