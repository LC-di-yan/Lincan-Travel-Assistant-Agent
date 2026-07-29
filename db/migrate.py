"""JSON -> PostgreSQL 数据迁移（一次性脚本）"""
import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path


def _to_date(s):
    """将日期字符串转为 datetime.date，无效值返回 None"""
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _to_datetime(s):
    """将时间戳字符串转为 datetime，无效值返回 None"""
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MEMORY_DIR = Path("data/memory")
CONFIG_PATH = Path("data/plugin_config.json")


async def migrate():
    from db.connection import get_pool

    pool = await get_pool()
    if pool is None:
        print("ALIGO_DATABASE_URL not set, nothing to migrate.")
        return

    # 读取并执行 schema
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        await pool.execute(f.read())
    logger.info("Schema applied")

    # 迁移用户数据
    if not MEMORY_DIR.exists():
        logger.info("No data/memory/ directory found, skipping user data migration")
    else:
        for json_file in MEMORY_DIR.glob("*.json"):
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            user_id = data.get("user_id", json_file.stem)
            logger.info(f"Migrating user: {user_id}")

            await pool.execute(
                "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                user_id,
            )

            for pref in data.get("preferences", []):
                await pool.execute(
                    """
                    INSERT INTO preferences(user_id, pref_type, pref_value)
                    VALUES($1, $2, $3::jsonb)
                    ON CONFLICT(user_id, pref_type) DO UPDATE SET pref_value=$3::jsonb, updated_at=NOW()
                    """,
                    user_id,
                    pref["type"],
                    json.dumps(pref["value"], ensure_ascii=False),
                )

            for msg in data.get("chat_history", []):
                await pool.execute(
                    """
                    INSERT INTO chat_messages(user_id, session_id, role, content, created_at)
                    VALUES($1, $2, $3, $4, $5)
                    """,
                    user_id,
                    msg.get("session_id"),
                    msg["role"],
                    msg["content"],
                    _to_datetime(msg.get("timestamp")),
                )

            for trip in data.get("trip_history", []):
                extra = {
                    k: v
                    for k, v in trip.items()
                    if k
                    not in (
                        "trip_id",
                        "origin",
                        "destination",
                        "start_date",
                        "end_date",
                        "purpose",
                        "timestamp",
                    )
                }
                await pool.execute(
                    """
                    INSERT INTO trip_history(user_id, trip_id, origin, destination, start_date, end_date, purpose, extra, created_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)
                    """,
                    user_id,
                    trip.get("trip_id", ""),
                    trip.get("origin"),
                    trip.get("destination"),
                    _to_date(trip.get("start_date")),
                    _to_date(trip.get("end_date")),
                    trip.get("purpose"),
                    json.dumps(extra, ensure_ascii=False),
                    _to_datetime(trip.get("timestamp")),
                )

            for exp in data.get("expenses", []):
                await pool.execute(
                    """
                    INSERT INTO expenses(user_id, expense_id, category, amount, currency, description, expense_date, created_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    user_id,
                    exp.get("id", ""),
                    exp.get("category", "其他"),
                    exp.get("amount", 0),
                    exp.get("currency", "CNY"),
                    exp.get("description", ""),
                    _to_date(exp.get("date")),
                    _to_datetime(exp.get("timestamp")),
                )

            total_queries = data.get("statistics", {}).get("total_queries", 0)
            await pool.execute(
                "UPDATE users SET query_count=$1 WHERE user_id=$2",
                total_queries,
                user_id,
            )

            logger.info(
                f"  Done: {len(data.get('chat_history', []))} msgs, "
                f"{len(data.get('expenses', []))} expenses"
            )

    # 迁移 plugin_config
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            plugins = json.load(f)
        await pool.execute(
            "INSERT INTO users(user_id) VALUES('default_user') ON CONFLICT DO NOTHING",
        )
        for name, cfg in plugins.items():
            await pool.execute(
                """
                INSERT INTO plugin_config(user_id, plugin_name, enabled)
                VALUES('default_user', $1, $2)
                ON CONFLICT(user_id, plugin_name) DO UPDATE SET enabled=$2, updated_at=NOW()
                """,
                name,
                cfg.get("enabled", True),
            )
        logger.info(f"  Migrated {len(plugins)} plugin configs")

    from db.connection import close_pool
    await close_pool()
    logger.info("Migration complete")


if __name__ == "__main__":
    asyncio.run(migrate())
