"""个人行程仓库：按所有者读，写入与既有账本共享用户级事务。"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from context.long_term_memory import LongTermMemory
from utils.json_store import validate_user_id


@dataclass
class PersonalData:
    plans: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)
    operations: dict = field(default_factory=dict)
    matching_history: list = field(default_factory=list)
    recent_history: list = field(default_factory=list)
    schedule: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    expenses: list = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    favorites: dict = field(default_factory=dict)


async def trip_repository(user_id):
    from db.connection import get_pool

    pool = await get_pool()
    return PostgresTrips(user_id, pool) if pool is not None else JsonTrips(user_id)


class JsonTrips:
    def __init__(self, user_id, storage: str | Path = "data/memory"):
        self.user_id, self.storage = validate_user_id(user_id), storage

    async def run(self, command, *, write=False, version_ids=(), history_id=None, recent_history=False, schedule=False,
                  ledger=False, expense_ref=None, profile=False, favorites=False):
        def read_or_write(root):
            namespace = root.setdefault("personal_v1", {})
            preference_rows = root.get("preferences", []) if profile else []
            prefs = {row["type"]: row["value"] for row in preference_rows
                     if isinstance(row, dict) and isinstance(row.get("type"), str) and "value" in row}
            old_preferences = deepcopy(prefs) if write and profile else prefs
            data = PersonalData(
                plans=namespace.setdefault("plans", {}),
                versions=namespace.setdefault("versions", {}),
                operations=namespace.setdefault("operations", {}),
                matching_history=[row for row in root.get("trip_history", [])
                                  if history_id is not None and isinstance(row, dict) and row.get("trip_id") == history_id][:2],
                recent_history=_recent_json_history(root) if recent_history else [],
                schedule=namespace.setdefault("schedule", {}) if schedule else {},
                state=namespace.setdefault("state", {}) if schedule or profile else {},
                expenses=root.setdefault("expenses", []) if ledger else [],
                preferences=prefs,
                favorites=namespace.setdefault("favorites", {}) if favorites else {},
            )
            result = command(data)
            if write and profile and data.preferences != old_preferences:
                changes = {key for key in set(data.preferences) | set(old_preferences)
                           if data.preferences.get(key) != old_preferences.get(key) or (key in data.preferences) != (key in old_preferences)}
                root["preferences"] = [
                    row for row in preference_rows if not isinstance(row, dict) or row.get("type") not in changes
                ] + [{"type": key, "value": data.preferences[key]} for key in sorted(changes & data.preferences.keys())]
            return result

        def in_thread():
            memory = LongTermMemory(self.user_id, self.storage)
            return memory.personal_transaction(read_or_write, write=write)

        return await asyncio.to_thread(in_thread)


def _recent_json_history(root):
    from collections import Counter

    rows = [row for row in root.get("trip_history", []) if isinstance(row, dict) and isinstance(row.get("trip_id"), str)]
    counts = Counter(row["trip_id"] for row in rows)
    return [{**row, "ambiguous": counts[row["trip_id"]] > 1} for row in reversed(rows[-30:])]


class PostgresTrips:
    def __init__(self, user_id, pool):
        self.user_id, self.pool = validate_user_id(user_id), pool

    async def run(self, command, *, write=False, version_ids=(), history_id=None, recent_history=False, schedule=False,
                  ledger=False, expense_ref=None, profile=False, favorites=False):
        owner = self.user_id
        async with self.pool.acquire() as conn, conn.transaction(
            isolation="read_committed" if write else "repeatable_read", readonly=not write,
        ):
            if write:
                await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", owner)
                await conn.fetchval("SELECT user_id FROM users WHERE user_id=$1 FOR UPDATE", owner)

            plans = {str(row["plan_id"]): row["metadata"] for row in await conn.fetch(
                "SELECT plan_id,metadata FROM trip_plans WHERE user_id=$1", owner,
            )}
            versions = {}
            if version_ids:
                for row in await conn.fetch(
                    "SELECT plan_id,version_no,payload FROM trip_plan_versions WHERE user_id=$1 AND plan_id=ANY($2::uuid[])",
                    owner, [UUID(str(value)) for value in version_ids],
                ):
                    versions.setdefault(str(row["plan_id"]), {})[str(row["version_no"])] = row["payload"]
            operations = {row["operation_key"]: row["payload"] for row in await conn.fetch(
                "SELECT operation_key,payload FROM trip_plan_operations WHERE user_id=$1", owner,
            )} if write else {}
            history = [dict(row) for row in await conn.fetch(
                """SELECT trip_id,origin,destination,start_date,end_date,purpose FROM trip_history
                   WHERE user_id=$1 AND trip_id=$2 LIMIT 2""", owner, history_id,
            )] if history_id else []
            recent = [dict(row) for row in await conn.fetch(
                """SELECT trip_id,origin,destination,start_date,end_date,purpose,
                          count(*) OVER (PARTITION BY trip_id)>1 AS ambiguous
                   FROM trip_history WHERE user_id=$1 ORDER BY created_at DESC,id DESC LIMIT 30""", owner,
            )] if recent_history else []
            calendar = {}
            state = {}
            if schedule or profile:
                state = await conn.fetchval("SELECT state FROM personal_plan_state WHERE user_id=$1", owner) or {}
            if schedule:
                for row in await conn.fetch(
                    "SELECT plan_id,version_no,payload FROM trip_schedule_blocks WHERE user_id=$1 ORDER BY block_id", owner,
                ):
                    calendar.setdefault(str(row["plan_id"]), {"version": row["version_no"], "events": []})["events"].append(row["payload"])
            expense_rows = []
            if ledger:
                query = """SELECT id AS row_id, expense_id AS id, category, amount, currency, description,
                                  expense_date AS date, created_at AS timestamp, entry_ref, trip_plan_id
                           FROM expenses WHERE user_id=$1"""
                args = [owner]
                if expense_ref is not None:
                    query += " AND entry_ref=$2"
                    args.append(UUID(str(expense_ref)))
                if write:
                    query += " FOR UPDATE"
                expense_rows = [dict(row) for row in await conn.fetch(query, *args)]
            prefs = {row["pref_type"]: row["pref_value"] for row in await conn.fetch(
                "SELECT pref_type,pref_value FROM preferences WHERE user_id=$1" + (" FOR UPDATE" if write else ""), owner,
            )} if profile else {}
            bookmarks = {str(row["favorite_id"]): row["payload"] for row in await conn.fetch(
                "SELECT favorite_id,payload FROM personal_favorites WHERE user_id=$1", owner,
            )} if favorites else {}
            data = PersonalData(plans, versions, operations, history, recent, calendar, state, expense_rows, prefs, bookmarks)
            original = deepcopy(data) if write else None
            result = command(data)
            if original is not None:
                await self._persist(conn, original, data)
            return result

    async def _persist(self, conn, original, data):
        owner = self.user_id
        for key, item in data.plans.items():
            if item != original.plans.get(key):
                await conn.execute(
                    """INSERT INTO trip_plans(user_id,plan_id,revision,lifecycle,updated_at,metadata)
                       VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(user_id,plan_id) DO UPDATE
                       SET revision=EXCLUDED.revision,lifecycle=EXCLUDED.lifecycle,
                           updated_at=EXCLUDED.updated_at,metadata=EXCLUDED.metadata""",
                    owner, UUID(key), item["revision"], item["lifecycle"], datetime.fromisoformat(item["updated_at"]), item,
                )
        for key, versions in data.versions.items():
            previous = original.versions.get(key, {})
            for seq, item in versions.items():
                if seq in previous:
                    if previous[seq] != item:
                        raise RuntimeError("已有行程版本不可修改")
                    continue
                await conn.execute(
                    """INSERT INTO trip_plan_versions(user_id,plan_id,version_no,parent_version_no,payload)
                       VALUES($1,$2,$3,$4,$5)""", owner, UUID(key), int(seq), item["parent_version"], item,
                )
        for key in original.operations.keys() - data.operations.keys():
            await conn.execute("DELETE FROM trip_plan_operations WHERE user_id=$1 AND operation_key=$2", owner, key)
        for key, item in data.operations.items():
            if item != original.operations.get(key):
                await conn.execute(
                    """INSERT INTO trip_plan_operations(user_id,operation_key,payload) VALUES($1,$2,$3)
                       ON CONFLICT(user_id,operation_key) DO UPDATE SET payload=EXCLUDED.payload""", owner, key, item,
                )
        if data.state != original.state:
            await conn.execute(
                """INSERT INTO personal_plan_state(user_id, calendar_revision, state) VALUES($1,$2,$3)
                   ON CONFLICT(user_id) DO UPDATE SET calendar_revision=EXCLUDED.calendar_revision,state=EXCLUDED.state""",
                owner, data.state.get("calendar_revision", 0), data.state,
            )
        changed_plans = original.schedule.keys() | data.schedule.keys()
        for key in sorted(changed_plans):
            block = data.schedule.get(key)
            if block == original.schedule.get(key):
                continue
            await conn.execute("DELETE FROM trip_schedule_blocks WHERE user_id=$1 AND plan_id=$2", owner, UUID(key))
            if block and block["events"]:
                await conn.executemany(
                    """INSERT INTO trip_schedule_blocks(user_id,plan_id,version_no,block_id,start_at,end_at,local_date,payload)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                    [(owner, UUID(key), block["version"], UUID(event["event_id"]),
                      datetime.fromisoformat(event["start_at"]) if event["start_at"] else None,
                      datetime.fromisoformat(event["end_at"]) if event["end_at"] else None,
                      datetime.fromisoformat(event["local_date"]).date() if event["local_date"] else None, event)
                     for event in block["events"]],
                )
        before = {item["row_id"]: item["trip_plan_id"] for item in original.expenses}
        for row in data.expenses:
            if row["trip_plan_id"] != before.get(row["row_id"]):
                await conn.execute("UPDATE expenses SET trip_plan_id=$3 WHERE user_id=$1 AND id=$2",
                                   owner, row["row_id"], UUID(str(row["trip_plan_id"])) if row["trip_plan_id"] else None)
        for key in original.preferences.keys() - data.preferences.keys():
            await conn.execute("DELETE FROM preferences WHERE user_id=$1 AND pref_type=$2", owner, key)
        for key, value in data.preferences.items():
            if key not in original.preferences or value != original.preferences[key]:
                await conn.execute(
                    """INSERT INTO preferences(user_id,pref_type,pref_value) VALUES($1,$2,$3)
                       ON CONFLICT(user_id,pref_type) DO UPDATE SET pref_value=EXCLUDED.pref_value,updated_at=NOW()""", owner, key, value,
                )
        for key in original.favorites.keys() - data.favorites.keys():
            await conn.execute("DELETE FROM personal_favorites WHERE user_id=$1 AND favorite_id=$2", owner, UUID(key))
        for key, value in data.favorites.items():
            if key not in original.favorites:
                await conn.execute(
                    """INSERT INTO personal_favorites(user_id,favorite_id,kind,dedupe_key,plan_id,version_no,payload)
                       VALUES($1,$2,$3,$4,$5,$6,$7)""", owner, UUID(key), value["kind"], value["dedupe_key"],
                    UUID(value["ref"]["plan_id"]), value["ref"]["version"], value,
                )
