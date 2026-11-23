import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from context.long_term_memory import PostgresLongTermMemory
from db.connection import _init_connection


@pytest.mark.integration
async def test_postgres_ledger_command_commits_once_and_preserves_other_users():
    dsn = os.environ.get("ALIGO_TEST_LEDGER_PG_DSN")
    if not dsn:
        pytest.skip("需要本次自建的本机 PostgreSQL aligo_audit 测试库")
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"127.0.0.1", "::1"} and parsed.path == "/aligo_audit"
    import asyncpg

    root = Path(__file__).resolve().parents[1]
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_init_connection)
    async with pool:
        schema = (root / "db" / "schema.sql").read_text(encoding="utf-8")
        legacy = schema.split("-- 费用确认提案与幂等回执", 1)[0]
        await pool.execute(legacy)
        old = PostgresLongTermMemory("ledger_existing_fixture", pool)
        await old.add_expense({"id": "old_expense", "amount": 91.25, "currency": "EUR", "category": "住宿"})
        before = await old.get_expenses()
        await pool.execute(schema)
        assert before == await old.get_expenses()
        owner = PostgresLongTermMemory("ledger_fixture_a", pool)
        same_owner = PostgresLongTermMemory("ledger_fixture_a", pool)
        other = PostgresLongTermMemory("ledger_fixture_b", pool)
        session = "isolated"
        token = "ab" * 12
        record = {"kind": "record", "request_hash": "synthetic",
                  "items": [{"category": "交通", "amount": 30, "currency": "CNY", "description": "打车", "date": "2026-11-20"},
                            {"category": "餐饮", "amount": 50, "currency": "USD", "description": "午餐", "date": "2026-11-20"}]}
        p1, p2 = await asyncio.gather(*(backend.expense_operation(session, token, "stage", record) for backend in (owner, same_owner)))
        assert p1 == p2 and p1["state"] == "pending" and not await owner.get_expenses()
        assert (await other.expense_operation(session, token, "confirm"))["state"] == "not_found"
        assert (await owner.expense_operation("other_session", token, "confirm"))["state"] == "not_found"
        r1, r2 = await asyncio.gather(*(backend.expense_operation(session, token, "confirm") for backend in (owner, same_owner)))
        assert r1 == r2 and r1["state"] == "committed"
        rows = sorted(await owner.get_expenses(), key=lambda row: row["amount"])
        assert [(row["amount"], row["currency"]) for row in rows] == [(30, "CNY"), (50, "USD")]
        assert not await other.get_expenses()

        from utils.expense_commands import expense_snapshot

        expected = expense_snapshot(rows[0])
        edit_token, erase_token = "cd" * 12, "de" * 12
        await owner.expense_operation(session, edit_token, "stage",
                                      {"kind": "update", "request_hash": "a", "expected": expected, "amount": 35, "currency": "CNY"})
        await owner.expense_operation(session, erase_token, "stage",
                                      {"kind": "delete", "request_hash": "b", "expected": expected})
        assert (await owner.expense_operation(session, edit_token, "confirm"))["state"] == "committed"
        assert (await owner.expense_operation(session, erase_token, "confirm"))["state"] == "conflict"
        row = next(item for item in await owner.get_expenses() if item["id"] == expected["id"])
        erase_token = "ef" * 12
        await owner.expense_operation(session, erase_token, "stage",
                                      {"kind": "delete", "request_hash": "c", "expected": expense_snapshot(row)})
        assert (await owner.expense_operation(session, erase_token, "confirm"))["receipt"]["deleted_id"] == row["id"]
        assert (await owner.expense_operation(session, token, "confirm")) == r1
        assert len(await owner.get_expenses()) == 1

        fail_token = "12" * 12
        invalid_batch = {**record, "items": [record["items"][0], dict(record["items"][1], category="x" * 33)]}
        await owner.expense_operation(session, fail_token, "stage", invalid_batch)
        with pytest.raises(asyncpg.StringDataRightTruncationError):
            await owner.expense_operation(session, fail_token, "confirm")
        assert len(await owner.get_expenses()) == 1
        assert (await owner.expense_operation(session, fail_token, "lookup"))["state"] == "pending"
