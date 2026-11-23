"""签名身份、用户归属与真实记账接口的离线集成回归。"""
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
import httpx
import pytest

from server import auth


@pytest.fixture
def application(monkeypatch, tmp_path):
    import server.session as sessions
    from agents.lazy_agent_registry import LazyAgentRegistry
    from context.memory_manager import MemoryManager
    from server.routes import chat, memory, suggestions

    monkeypatch.setenv("ALIGO_SESSION_SECRET", "测试签名密钥" * 8)
    monkeypatch.setenv("ALIGO_ENABLE_LLM_SUGGESTIONS", "0")
    auth.signing_key.cache_clear()
    monkeypatch.setattr(sessions, "build_chat_model", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(sessions, "MemoryManager", lambda **kwargs: MemoryManager(storage_path=str(tmp_path / "memory"), **kwargs))
    monkeypatch.setattr(LazyAgentRegistry, "CONFIG_PATH", tmp_path / "plugin_config.json")
    manager = sessions.SessionManager()
    manager._initialized = True
    monkeypatch.setattr(chat, "session_manager", manager)
    monkeypatch.setattr(memory, "session_manager", manager)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(memory.router)
    app.include_router(suggestions.router)
    yield SimpleNamespace(app=app, manager=manager)
    auth.signing_key.cache_clear()


@asynccontextmanager
async def browser(application):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application.app), base_url="http://test") as client:
        result = await client.post("/api/identity")
        assert result.status_code == 200
        yield client, result.json()["user_id"]


@pytest.mark.asyncio
async def test_anonymous_access_is_denied(application):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application.app), base_url="http://test") as client:
        for path in ("/api/context", "/api/history", "/api/preferences", "/api/expenses", "/api/plugins"):
            assert (await client.get(path)).status_code == 401
        assert (await client.post("/api/chat", json={"message": "测试"})).status_code == 401
        assert (await client.post("/api/session/new", json={})).status_code == 401
        assert (await client.post("/api/suggestions", json={"prompt": "测试"})).status_code == 401


@pytest.mark.asyncio
async def test_different_browsers_cannot_claim_each_others_data(application):
    async with browser(application) as (first, first_id), browser(application) as (second, second_id):
        assert first_id != second_id
        saved = await first.put("/api/preferences", json={"pref_type": "home_location", "value": "北京"})
        assert saved.status_code == 200
        for path in ("context", "preferences", "history", "expenses"):
            assert (await second.get(f"/api/{path}", params={"user_id": first_id})).status_code == 403
        assert (await second.put("/api/preferences", params={"user_id": first_id}, json={"pref_type": "home_location", "value": "伪造"})).status_code == 403
        assert (await second.post("/api/session/new", json={"user_id": first_id})).status_code == 403
        assert (await second.post("/api/chat", json={"user_id": first_id, "message": "记一笔打车50元"})).status_code == 403
        assert (await second.get("/api/preferences")).json()["preferences"] == {}
        assert (await first.get("/api/preferences")).json()["preferences"]["home_location"] == "北京"


@pytest.mark.asyncio
async def test_bootstrap_reuses_identity_and_uses_protected_cookie(application):
    async with browser(application) as (client, user_id):
        response = await client.post("/api/identity", json={"user_id": "default_user"})
        assert response.json()["user_id"] == user_id
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
        assert response.headers["cache-control"] == "no-store"
        session = await client.post("/api/session/new", json={})
        assert session.json()["user_id"] == user_id


@pytest.mark.asyncio
async def test_untrusted_origin_cannot_bootstrap_or_write(application):
    async with browser(application) as (client, _):
        headers = {"Origin": "https://untrusted.example"}
        assert (await client.post("/api/identity", headers=headers)).status_code == 403
        assert (await client.put("/api/preferences", headers=headers, json={"pref_type": "home_location", "value": "伪造"})).status_code == 403


@pytest.mark.asyncio
async def test_forged_or_expired_identity_is_rejected(application, monkeypatch):
    async with browser(application) as (client, user_id):
        token = client.cookies.get(auth.COOKIE_NAME)
        with pytest.raises(ValueError):
            auth.issue_identity("../outside")
        assert auth.read_identity(token.replace(user_id, "default_user")) is None
        real_time = auth.time.time()
        monkeypatch.setattr(auth.time, "time", lambda: real_time + auth.MAX_AGE + 1)
        assert (await client.get("/api/context")).status_code == 401


def test_signing_key_persists_across_server_restarts(monkeypatch, tmp_path):
    monkeypatch.delenv("ALIGO_SESSION_SECRET", raising=False)
    monkeypatch.setenv("ALIGO_AUTH_KEY_PATH", str(tmp_path / "auth" / "key.json"))
    auth.signing_key.cache_clear()
    try:
        token = auth.issue_identity("test_user")
        auth.signing_key.cache_clear()
        assert auth.read_identity(token) == "test_user"
    finally:
        auth.signing_key.cache_clear()


@pytest.mark.asyncio
async def test_full_chat_preserves_expense_currency_date_and_total(application):
    async with browser(application) as (client, user_id):
        session = (await client.post("/api/session/new", json={})).json()
        response = await client.post("/api/chat", json={"session_id": session["session_id"], "message": "昨天打车花了50美元，记一笔"})
        assert response.status_code == 200
        events = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        complete = next(event for event in events if event.get("status") == "completed")
        preview = complete["results"][0]["data"]
        assert preview["action"] == "preview"
        assert (await client.get("/api/expenses")).json()["expenses"] == []
        response = await client.post("/api/chat", json={"session_id": session["session_id"], "message": preview["confirmation_command"]})
        assert response.status_code == 200
        events = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        complete = next(event for event in events if event.get("status") == "completed")
        expense = complete["results"][0]["data"]
        assert expense["expense"]["currency"] == "USD"
        assert expense["total_after"] == 50
        expenses = (await client.get("/api/expenses")).json()
        assert expenses["total"] == 50 and expenses["currency"] == "USD"
        assert expenses["totals_by_currency"] == {"USD": 50}
        owner = await application.manager.get_or_create(user_id, session["session_id"])
        owner.model.assert_not_called()


@pytest.mark.asyncio
async def test_plugin_disable_applies_to_cached_alias_and_other_session(application):
    async with browser(application) as (client, user_id):
        first = (await client.post("/api/session/new", json={})).json()["session_id"]
        second = (await client.post("/api/session/new", json={})).json()["session_id"]
        cached = await application.manager.get_or_create(user_id, first)
        cached.orchestrator.agent_registry["expense_tracking"]
        assert (await client.put("/api/plugins", json={"name": "expense-tracker", "enabled": False})).status_code == 200
        assert cached.orchestrator.agent_registry.get("expense_tracking") is None
        other = await application.manager.get_or_create(user_id, second)
        assert other.orchestrator.agent_registry.get("expense_tracking") is None
        plugins = (await client.get("/api/plugins")).json()["plugins"]
        assert next(plugin for plugin in plugins if plugin["name"] == "expense-tracker")["enabled"] is False
    async with browser(application) as (different, _):
        plugins = (await different.get("/api/plugins")).json()["plugins"]
        assert next(plugin for plugin in plugins if plugin["name"] == "expense-tracker")["enabled"] is True


@pytest.mark.asyncio
async def test_suggestions_disabled_by_default_and_prompt_is_bounded(application):
    async with browser(application) as (client, _):
        assert (await client.post("/api/suggestions", json={"prompt": "测试"})).json() == {"content": ""}
        assert (await client.post("/api/suggestions", json={"prompt": "测" * 6001})).status_code == 422


@pytest.mark.asyncio
async def test_enabled_suggestions_use_only_server_model(application, monkeypatch):
    from unittest.mock import AsyncMock
    import utils.llm_failover as failover
    model = AsyncMock(return_value={"text": '[{"text":"查询天气"}]'})
    monkeypatch.setattr(failover, "build_chat_model", lambda *args, **kwargs: model)
    monkeypatch.setenv("ALIGO_ENABLE_LLM_SUGGESTIONS", "1")
    async with browser(application) as (client, _):
        response = await client.post("/api/suggestions", json={"prompt": "测试"})
        assert "查询天气" in response.json()["content"]
        model.assert_awaited_once()
