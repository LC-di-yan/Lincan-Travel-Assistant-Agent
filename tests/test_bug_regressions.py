"""缺陷修复的离线回归测试；只使用临时存储和模拟上游。"""

import asyncio
import importlib.util
import sys
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from context.long_term_memory import LongTermMemory
from context.memory_manager import MemoryManager
from context.session_focus_state import SessionFocusState
from server.models import ChatRequest
from utils.as_compat import mk_msg, msg_json
from utils.circuit_breaker import CircuitBreaker


def load_skill(name):
    """按真实加载方式导入技能，避免修改产品目录。"""
    path = ROOT / ".claude" / "skills" / name / "script" / "agent.py"
    spec = importlib.util.spec_from_file_location("audit_" + name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def manager(monkeypatch, tmp_path):
    """只替换模型构造和存储位置，保留真实会话管理逻辑。"""
    import server.session as session_module

    monkeypatch.setattr(session_module, "build_chat_model", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(
        session_module, "MemoryManager",
        lambda **kwargs: MemoryManager(storage_path=str(tmp_path / "memory"), **kwargs),
    )
    from agents.lazy_agent_registry import LazyAgentRegistry
    monkeypatch.setattr(LazyAgentRegistry, "CONFIG_PATH", tmp_path / "plugin_config.json")
    instance = session_module.SessionManager()
    instance._initialized = True
    instance._cache_layer = None
    return instance


def test_user_id_must_not_escape_storage_directory(tmp_path):
    storage = tmp_path / "memory"
    with pytest.raises(ValueError):
        LongTermMemory("../outside", str(storage))
    assert not (tmp_path / "outside.json").exists()


@pytest.mark.asyncio
async def test_private_context_requires_user_authentication(manager, monkeypatch):
    import server.routes.memory as routes

    monkeypatch.setattr(routes, "session_manager", manager)
    victim = await manager.get_or_create("audit_victim", "victim-session")
    victim.memory_manager.long_term.save_preference("home_location", "测试用私人地址")
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/context", params={"user_id": "audit_victim"})
    assert response.status_code in (401, 403), f"无认证即可读取他人上下文，状态码 {response.status_code}"


@pytest.mark.asyncio
async def test_cors_must_reject_untrusted_origin():
    from server.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options("/api/preferences", headers={
            "Origin": "https://untrusted-audit.example",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        })
    assert response.headers.get("access-control-allow-origin") != "https://untrusted-audit.example", "任意网站通过跨域检查"


@pytest.mark.asyncio
async def test_sessions_of_same_user_must_not_overwrite_preferences(manager, tmp_path):
    first = await manager.get_or_create("audit_same_user", "first")
    second = await manager.get_or_create("audit_same_user", "second")
    first.memory_manager.long_term.save_preference("home_location", "北京")
    await second.memory_manager.add_message_async("user", "测试消息")
    reread = LongTermMemory("audit_same_user", str(tmp_path / "memory"))
    assert reread.get_preference("home_location") == "北京", "另一会话保存聊天时覆盖了已保存偏好"


@pytest.mark.asyncio
async def test_memory_query_accepts_single_message_from_orchestrator():
    agent = load_skill("memory-query").MemoryQueryAgent(model=AsyncMock(return_value={"text": "测试用历史回答"}))
    response = await agent.reply(mk_msg("Orchestrator", {"context": {"rewritten_query": "我之前说过什么偏好"}}, role="user"))
    result = msg_json(response)
    assert result.get("message") != "无法获取用户查询", "编排器传入单条消息时查询被丢弃"


@pytest.mark.asyncio
async def test_session_creation_failure_returns_error_event(monkeypatch):
    import server.routes.chat as routes

    monkeypatch.setattr(routes, "session_manager", SimpleNamespace(get_or_create=AsyncMock(side_effect=RuntimeError("测试初始化失败"))))
    response = await routes.chat(ChatRequest(user_id="audit", message="测试"), current_user="audit")
    events = [event async for event in response.body_iterator]
    assert events[0]["event"] == "error", "初始化失败应返回可解析的错误事件"


@pytest.mark.asyncio
@pytest.mark.parametrize("close_at_yield", [False, True])
async def test_disconnected_chat_cancels_orchestration(monkeypatch, tmp_path, close_at_yield):
    import server.routes.chat as routes

    class WaitingOrchestrator:
        """模拟进行中的模型请求，使用事件而非真实网络等待。"""

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.task = None

        async def reply(self, message):
            self.task = asyncio.current_task()
            self.started.set()
            await self.result_queue.put({"type": "agent_start", "agent_name": "information_query"})
            await self.release.wait()
            return mk_msg("OrchestrationAgent", {"status": "completed", "results": []})

    orchestrator = WaitingOrchestrator()
    intention = {"intents": [{"type": "information_query"}], "key_entities": {},
                 "agent_schedule": [{"agent_name": "information_query", "priority": 1}]}
    session = SimpleNamespace(
        session_id="audit", circuit_breaker=CircuitBreaker(), focus_state=SessionFocusState(),
        memory_manager=MemoryManager("audit_cancel", "audit", str(tmp_path)),
        intention_agent=SimpleNamespace(reply=AsyncMock(return_value=mk_msg("IntentionAgent", intention))),
        orchestrator=orchestrator, chat_lock=asyncio.Lock(), pending_intention=None,
        long_term_summary="", messages_since_summary=0,
    )
    monkeypatch.setattr(routes, "session_manager", SimpleNamespace(get_or_create=AsyncMock(return_value=session)))
    response = await routes.chat(ChatRequest(user_id="audit_cancel", message="北京天气"), current_user="audit_cancel")

    async def consume():
        async for event in response.body_iterator:
            if close_at_yield and event.get("event") == "agent_start":
                return

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(orchestrator.started.wait(), 2)
        if close_at_yield:
            await consumer
            await response.body_iterator.aclose()
        else:
            consumer.cancel()
            with suppress(asyncio.CancelledError):
                await consumer
        assert orchestrator.task.done(), "流已断开、会话锁已释放，但后台编排仍在运行"
        assert not session.chat_lock.locked()
    finally:
        consumer.cancel()
        if orchestrator.task:
            orchestrator.task.cancel()
            with suppress(asyncio.CancelledError):
                await orchestrator.task


def test_disabling_plugin_blocks_already_cached_alias(tmp_path):
    from agents.lazy_agent_registry import LazyAgentRegistry

    cached_agent = object()
    registry = LazyAgentRegistry(model=None, cache={"expense_tracking": cached_agent})
    registry.CONFIG_PATH = tmp_path / "plugin_config.json"
    registry.set_plugin_enabled("expense-tracker", False)
    assert registry.get("expense_tracking") is None, "禁用插件后仍返回旧别名缓存实例"


@pytest.mark.asyncio
async def test_recorded_total_must_not_count_new_expense_twice(tmp_path):
    memory = MemoryManager("audit_expense", "audit", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    preview = await _authorized_expense(agent, "记一笔打车费50元")
    assert memory.long_term.get_expenses() == []
    result = await _authorized_expense(agent, preview["confirmation_command"])
    assert result["total_after"] == 50, "只记一笔 50 元，返回累计金额 100 元"


async def _authorized_expense(agent, text):
    from utils.expense_commands import expense_execution

    with expense_execution(text, "audit"):
        return msg_json(await agent.reply(mk_msg("user", text, role="user")))


@pytest.mark.asyncio
async def test_fast_expense_preserves_currency_and_date(tmp_path):
    from agents.intention_agent import _fast_match

    query = "昨天打车花了50美元，记一笔"
    intention = _fast_match(query)
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=MemoryManager("audit_foreign", "audit", str(tmp_path)))
    response = await agent.reply(mk_msg("Orchestrator", {"context": {"rewritten_query": query}, "fast_expense": intention["fast_expense"]}, role="user"))
    expense = msg_json(response)["expense"]
    assert (expense["currency"], expense["date"]) == ("USD", (date.today() - timedelta(days=1)).isoformat()), "外币和昨天被改为人民币和今天"
    for text, expected in (("50USD", "USD"), ("50eur", "EUR"), ("50瑞士法郎", "CHF"), ("50RMB", "CNY")):
        match = _fast_match(f"昨天打车花了{text}，记一笔")
        assert match["fast_expense"]["currency"] == expected
    for text in ("50XYZ", "50马克", "50迪拉姆"):
        assert _fast_match(f"昨天打车花了{text}，记一笔") is None


def test_expense_summary_must_not_sum_different_currencies():
    agent = load_skill("expense-tracker").ExpenseTrackerAgent()
    result = agent._query_expenses({}, [{"amount": 100, "currency": "USD"}, {"amount": 100, "currency": "CNY"}])
    assert "¥200.00" not in result["answer"], "100 美元和 100 人民币不能直接汇总为 200 人民币"


@pytest.mark.parametrize("query", [
    "删除昨天打车50元那一笔", "查询打车50元这笔费用", "不要记打车50元",
    "午餐花了50万日元", "午餐花了20欧元，晚餐花了30欧元",
    "打车花了1,200元，记一笔", "午餐花了50€", "打车花了50元吗？",
])
def test_uncertain_expense_never_takes_the_write_shortcut(query):
    from agents.intention_agent import _fast_match

    assert not (_fast_match(query) or {}).get("fast_expense")


@pytest.mark.parametrize("extra", ["想住春熙路附近的酒店", "帮我查一下附近的客栈", "附近有哪些餐馆"])
def test_trip_shortcut_does_not_swallow_local_search(extra):
    from agents.intention_agent import _fast_match

    query = "下周从广州去成都旅游5天"
    assert _fast_match(query)["key_entities"]["duration_days"] == 5
    assert _fast_match(f"{query}，{extra}") is None


@pytest.mark.asyncio
async def test_delete_uses_the_confirmed_stable_id_even_if_another_row_moves(tmp_path):
    memory = MemoryManager("audit_window", "test", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    for i in range(22):
        memory.long_term.add_expense({"id": f"exp_{i}", "amount": 10})
    preview = await _authorized_expense(agent, "删除费用 exp_2")
    assert preview["action"] == "preview"
    memory.long_term.delete_expense(0)  # another session edits before confirmation
    result = await _authorized_expense(agent, preview["confirmation_command"])
    assert result["deleted_id"] == "exp_2"
    assert [e["id"] for e in memory.long_term.get_expenses()] == [
        f"exp_{i}" for i in range(1, 22) if i != 2
    ]
    assert await _authorized_expense(agent, preview["confirmation_command"]) == result
    assert len(memory.long_term.get_expenses()) == 20


@pytest.mark.parametrize("index", [False, None, "0", -1, 20])
@pytest.mark.asyncio
async def test_invalid_delete_index_leaves_ledger_untouched(tmp_path, index):
    memory = MemoryManager("audit_index", "test", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    memory.long_term.add_expense({"amount": 12})
    result = await _authorized_expense(agent, f"删除费用 {index}")
    assert result["action"] == "error" and len(memory.long_term.get_expenses()) == 1


def test_concurrent_preference_appends_retain_every_session_value(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    stores = [LongTermMemory("audit_append", str(tmp_path)) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda item: item[1].append_preference("hotel_brands", str(item[0]), unique=True), enumerate(stores)))
    stores[0].append_preference("hotel_brands", "1", unique=True)
    assert sorted(stores[0].get_preference("hotel_brands"), key=int) == list(map(str, range(12)))
    stores[0].append_preference("home_location", "北京")
    assert stores[1].get_preference("home_location") == "北京"
    stores[1].append_preference("home_location", "上海")
    assert stores[0].get_preference("home_location") == ["北京", "上海"]


def test_ambiguous_legacy_expense_ids_cannot_remove_multiple_rows(tmp_path):
    store = LongTermMemory("audit_duplicate", str(tmp_path))
    for amount in (10, 20):
        store.add_expense({"id": "legacy", "amount": amount})
    assert not store.delete_expense_by_id("legacy")
    assert len(store.get_expenses()) == 2


def test_rag_number_check_requires_whole_numeric_token():
    from rag_core.answerer import verify_numbers

    assert verify_numbers("住宿上限500元", "住宿上限1500元") == ["500元"], "数字子串被误认为与原文一致"


def test_trip_fast_route_does_not_drop_explicit_expense_request():
    from agents.intention_agent import _fast_match

    result = _fast_match("明天从北京去上海出差3天，顺便记一笔打车50元")
    if result is not None:
        scheduled = {item["agent_name"] for item in result["agent_schedule"]}
        assert scheduled & {"expense_tracking", "expense_tracker"}, "行程快路径吞掉明确的记账要求，费用不会写入"


@pytest.mark.asyncio
async def test_currency_network_wait_does_not_block_other_users(monkeypatch):
    from contextlib import asynccontextmanager

    module = load_skill("currency-converter")
    heartbeat = asyncio.Event()

    async def slow_request(request):
        await asyncio.sleep(0.15)
        return httpx.Response(200, json={"rates": {"CNY": 7}})

    @asynccontextmanager
    async def local_client(*args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow_request)) as client:
            yield client

    async def pulse():
        await asyncio.sleep(0.02)
        heartbeat.set()

    monkeypatch.setattr(module, "provider_client", local_client)
    pulse_task = asyncio.create_task(pulse())
    try:
        agent = module.CurrencyConverterAgent()
        result = msg_json(await agent.reply(mk_msg("Orchestrator", {"fast_currency": {"from_currency": "USD", "to_currency": "CNY", "amount": 100}}, role="user")))
        assert result["action"] == "convert"
        assert heartbeat.is_set(), "同步请求阻塞事件循环，其他用户请求无法前进"
    finally:
        await pulse_task
