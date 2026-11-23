import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from context.conversation_archive import LEGACY_CONVERSATION, public_message
from context.long_term_memory import LongTermMemory, PostgresLongTermMemory
from context.memory_manager import MemoryManager
from context.session_focus_state import SessionFocusState
from server.models import ChatRequest
from server.utils.conversation_transcript import Transcript


async def _call(method, *args, **kwargs):
    value = method(*args, **kwargs)
    return await value if hasattr(value, "__await__") else value


async def exercise_archive(storage, someone_else):
    await _call(storage.add_chat_message, "user", "出差费用", "old-alpha")
    await _call(storage.add_chat_message, "assistant", "历史可读摘要：上海", "old-alpha")
    await _call(storage.add_chat_message, "user", "另一轮去北京", "new-beta")
    await _call(storage.add_chat_message, "assistant", "结构化结果", "new-beta",
                presentation={"status": "complete", "results": [{"agent_name": "train_ticket", "data": {"answer": "车次信息"}}],
                              "checkpoint": {"focus": {"focus_city": "北京"}}})
    await _call(storage.add_chat_message, "user", "最早未分类记录", None)
    await _call(storage.add_chat_message, "system", "不供界面读取", "new-beta")
    await _call(storage.save_preference, "hotel_brands", "全季")
    await _call(storage.add_expense, {"id": "fee_001", "currency": "CNY", "amount": 32.50, "description": "合成费用"})
    results = await _call(storage.list_conversations, limit=2)
    assert [(item["id"], item["message_count"]) for item in results["items"]] == [
        (LEGACY_CONVERSATION, 1), ("new-beta", 2),
    ]
    assert (await _call(storage.list_conversations, before=results["next_before"]))["items"][0]["title"] == "出差费用"
    matched = await _call(storage.list_conversations, query="上海")
    assert [item["id"] for item in matched["items"]] == ["old-alpha"]
    latest = await _call(storage.read_conversation, "new-beta", limit=1)
    visible = public_message(latest["rows"][0])
    assert visible["results"][0]["data"]["answer"] == "车次信息"
    assert "checkpoint" not in visible and "presentation" not in visible
    older = await _call(storage.read_conversation, "new-beta", before=latest["next_before"], limit=1)
    assert older["rows"][0]["content"] == "另一轮去北京"
    assert await _call(someone_else.read_conversation, "new-beta") is None
    assert not (await _call(someone_else.list_conversations))["items"]
    assert (await _call(storage.get_preference, "hotel_brands")) == "全季"
    assert (await _call(storage.get_expenses))[0]["amount"] == 32.50
    assert all("presentation" not in row for row in await _call(storage.get_chat_history, session_id="new-beta"))


async def test_json_sessions_are_independent_and_share_the_existing_user_storage(tmp_path):
    storage = LongTermMemory("archive_owner", tmp_path)
    other = LongTermMemory("another_owner", tmp_path)
    await exercise_archive(storage, other)
    reopened = LongTermMemory("archive_owner", tmp_path)
    assert (reopened.read_conversation("old-alpha"))["rows"][-1]["content"] == "历史可读摘要：上海"
    saved = Path(storage.db_path).read_bytes()
    reopened.list_conversations()
    reopened.read_conversation(LEGACY_CONVERSATION)
    assert Path(storage.db_path).read_bytes() == saved


@pytest.mark.integration
async def test_postgres_sessions_reuse_the_same_database_and_support_old_text(tmp_path):
    dsn = os.environ.get("ALIGO_TEST_CONVERSATIONS_PG_DSN")
    if not dsn:
        pytest.skip("需要本机隔离的 aligo_conversations_dev_test 测试库")
    parts = urlsplit(dsn)
    assert parts.hostname in {"127.0.0.1", "::1"} and parts.path == "/aligo_conversations_dev_test"
    import asyncpg
    from db.connection import _init_connection

    root = Path(__file__).resolve().parents[1]
    schema = (root / "db/schema.sql").read_text(encoding="utf-8").replace("    presentation JSONB,\n", "")
    namespace = "archive_" + uuid4().hex
    async with asyncpg.create_pool(dsn, min_size=1, max_size=2, init=_init_connection,
                                   server_settings={"search_path": namespace}) as pool:
        await pool.execute(f'CREATE SCHEMA "{namespace}"')
        await pool.execute(schema)
        store = PostgresLongTermMemory("archive_owner", pool)
        await store.add_chat_message("assistant", "迁移前保留的文本", "pre-migration",
                                     presentation={"status": "complete"})
        assert (await store.read_conversation("pre-migration"))["rows"][0]["content"] == "迁移前保留的文本"
        migration = (root / "db/migrations/005_chat_presentation.sql").read_text(encoding="utf-8")
        await pool.execute(migration)
        await pool.execute(migration)
        assert (await store.read_conversation("pre-migration"))["rows"][0]["presentation"] is None
        scoped = PostgresLongTermMemory("scoped_owner", pool)
        await exercise_archive(scoped, PostgresLongTermMemory("another_owner", pool))


async def test_api_lists_only_the_signed_owners_conversations(tmp_path, monkeypatch):
    from server.app import app
    from server.auth import signing_key
    from server.routes import conversations

    async def use_temp(owner):
        return LongTermMemory(owner, tmp_path)

    monkeypatch.setattr(conversations, "archive_for_user", use_temp)
    monkeypatch.setenv("ALIGO_SESSION_SECRET", "s" * 32)
    signing_key.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://archive.test") as client, AsyncClient(
            transport=ASGITransport(app=app), base_url="https://archive.test",
        ) as stranger:
            assert (await client.get("/api/conversations")).status_code == 401
            owner = (await client.post("/api/identity")).json()["user_id"]
            await stranger.post("/api/identity")
            storage = LongTermMemory(owner, tmp_path)
            storage.add_chat_message("user", "上海行程", "restore123")
            storage.add_chat_message("assistant", "从哪个城市出发？", "restore123",
                                     presentation={"status": "clarification", "checkpoint": {"pending": {"do_not_expose": True}}})
            storage.add_chat_message("user", "早期对话", None)
            result = await client.get("/api/conversations", params={"q": "城市"})
            assert result.headers["cache-control"] == "private, no-store"
            assert [i["id"] for i in result.json()["items"]] == ["restore123"]
            query = await client.get("/api/conversations/restore123/messages")
            assert query.json()["messages"][-1]["content"] == "从哪个城市出发？"
            assert "do_not_expose" not in query.text
            assert (await client.get("/api/conversations/~legacy/messages")).json()["readonly"]
            assert (await stranger.get("/api/conversations/restore123/messages")).status_code == 404
            assert not (await stranger.get("/api/conversations")).json()["items"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://archive.test") as plain:
            await plain.post("/api/identity")
            assert (await plain.get("/api/conversations")).status_code == 403
    finally:
        signing_key.cache_clear()


def test_saved_cards_exclude_credentials_and_actions_that_cannot_be_replayed():
    events = Transcript()
    events.observe({"event": "complete", "data": json.dumps({"candidate_ref": "temporary",
        "results": [{"agent_name": "expense_tracking", "data": {"answer": "旧预览，确认费用 " + "a"*24,
                     "confirmation_command": "确认费用 " + "a"*24, "csrf_token": "unpublished",
                     "results": {"url": "https://example.test?key=hidden_key", "amount": 32.50}}}]})})
    text, display = events.assistant_message(SimpleNamespace())
    serialization = json.dumps(display, ensure_ascii=False)
    assert "a"*24 not in text and "hidden_key" not in serialization and "unpublished" not in serialization
    assert "32.5" in serialization and "temporary" not in serialization


async def test_chat_restores_a_pending_route_after_recreation_without_borrowing_another_conversation(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from agents.intention_agent import IntentionAgent
    from agents.orchestration_agent import OrchestrationAgent
    from server.routes import chat
    from utils.as_compat import mk_msg, msg_json
    from utils.circuit_breaker import CircuitBreaker

    model = AsyncMock(side_effect=AssertionError("本次测试不应调用模型"))
    calls = []

    class Rail:
        async def reply(self, message):
            calls.append(msg_json(message)["fast_train_ticket"])
            return mk_msg("rail", {"query_success": True, "answer": "测试列车", "results": {"trains": []}})

    def runtime(session_id):
        memory = MemoryManager("resuming_user", session_id, str(tmp_path))
        return SimpleNamespace(session_id=session_id, chat_lock=asyncio.Lock(), pending_intention=None, pending_since=0,
                               messages_since_summary=0, focus_state=SessionFocusState(), circuit_breaker=CircuitBreaker(),
                               memory_manager=memory, intention_agent=IntentionAgent(model=model),
                               orchestrator=OrchestrationAgent(agent_registry={"train_ticket": Rail()}, memory_manager=memory))

    allocated = {"rail-one": runtime("rail-one")}
    async def access(user, session):
        assert user == "resuming_user"
        return allocated[session]

    monkeypatch.setattr(chat, "session_manager", SimpleNamespace(get_or_create=access))
    async def send(session, text):
        response = await chat.chat(ChatRequest(session_id=session, message=text), "resuming_user")
        return [(chunk["event"], json.loads(chunk["data"])) async for chunk in response.body_iterator]

    assert (await send("rail-one", "查去北京的火车票，我想少换乘"))[-1][0] == "clarification"
    allocated["rail-two"] = runtime("rail-two")
    assert (await send("rail-two", "查去杭州的火车票"))[-1][0] == "clarification"
    allocated["rail-one"] = runtime("rail-one")
    assert (await send("rail-one", "上海"))[-1][0] == "clarification"
    allocated["rail-one"] = runtime("rail-one")
    assert (await send("rail-one", "明天"))[-1][0] == "complete"
    assert len(calls) == 1 and (calls[0]["from"], calls[0]["to"]) == ("上海", "北京")
    storage = LongTermMemory("resuming_user", tmp_path)
    assert [row["role"] for row in storage.read_conversation("rail-one")["rows"]] == ["user", "assistant"] * 3
    assert len(storage.read_conversation("rail-two")["rows"]) == 2
    model.assert_not_awaited()
