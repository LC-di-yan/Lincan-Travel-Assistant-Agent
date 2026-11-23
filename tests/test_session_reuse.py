"""会话复用回归测试。

2026-10-20 全量测试发现的两个 bug：
1. `get_or_create(user_id)` 不带 session_id 时每次都新建会话 → 短期记忆（10 轮）丢失。
2. `get_existing()` 取字典里第一个会话，可能是空壳 → 侧栏偏好/费用永远读到空快照。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.session import SessionManager  # noqa: E402

USER = "pytest_session_reuse"


@pytest.fixture()
def manager(monkeypatch, tmp_path):
    from context.memory_manager import MemoryManager
    from unittest.mock import MagicMock
    from agents.lazy_agent_registry import LazyAgentRegistry

    monkeypatch.setattr("server.session.build_chat_model", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("server.session.MemoryManager", lambda **kw: MemoryManager(storage_path=str(tmp_path / "memory"), **kw))
    monkeypatch.setattr(LazyAgentRegistry, "CONFIG_PATH", tmp_path / "plugin_config.json")
    mgr = SessionManager()
    mgr._initialized = True
    return mgr


def test_same_user_without_session_id_reuses_session(manager):
    async def scenario():
        a = await manager.get_or_create(USER)
        b = await manager.get_or_create(USER)
        return a, b

    a, b = asyncio.run(scenario())
    assert a is b, "同一用户不带 session_id 时应复用会话，否则短期记忆会丢"
    assert len(manager._sessions) == 1


def test_get_existing_returns_most_recent(manager):
    async def scenario():
        first = await manager.get_or_create(USER)
        await asyncio.sleep(0.01)
        second = await manager.get_or_create(USER, "explicit1")
        await asyncio.sleep(0.01)
        third = await manager.get_or_create(USER, "explicit2")
        return first, second, third, manager.get_existing(USER)

    first, second, third, latest = asyncio.run(scenario())
    assert latest is third, "get_existing 应返回最近活跃的会话，而不是第一个"
    assert {first.session_id, second.session_id, third.session_id} == {"explicit1", "explicit2", first.session_id}


def test_new_session_replaces_user_sessions(manager):
    async def scenario():
        old = await manager.get_or_create(USER, "old1")
        old.memory_manager.long_term.save_preference("hotel_brands", "全季")
        fresh = await manager.new_session(USER)
        return old, fresh, manager.get_existing(USER)

    old, fresh, latest = asyncio.run(scenario())
    assert fresh.session_id != old.session_id
    assert latest is fresh
    # 新会话仍应从磁盘读到刚写入的偏好
    assert "全季" in str(fresh.memory_manager.long_term.get_preference())


async def test_last_access_breaks_equal_clock_ticks_without_crossing_users(manager, monkeypatch):
    from types import SimpleNamespace
    import server.session as sessions

    monkeypatch.setattr(sessions, "time", SimpleNamespace(monotonic=lambda: 42.0))
    old = await manager.get_or_create(USER, "old1")
    fresh = await manager.new_session(USER)
    another = await manager.get_or_create("user_other", old.session_id)
    assert old.last_active == fresh.last_active == another.last_active
    assert manager.get_existing(USER) is fresh
    await manager.get_or_create(USER, old.session_id)
    assert manager.get_existing(USER) is old
    assert manager.get_existing("user_other") is another
