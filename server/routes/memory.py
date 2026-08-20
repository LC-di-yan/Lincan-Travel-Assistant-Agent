"""记忆相关 API — 历史行程、偏好、上下文、插件管理"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.models import PreferenceUpdate, SessionRequest
from server.session import session_manager

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.post("/api/session/new")
async def new_session(request: SessionRequest):
    session = await session_manager.new_session(request.user_id)
    return {"user_id": session.user_id, "session_id": session.session_id}


def _get_user_session(user_id: str):
    session = session_manager.get_existing(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session for this user")
    return session


def _is_pg(session) -> bool:
    """判断当前会话是否使用 PostgreSQL"""
    from context.long_term_memory import PostgresLongTermMemory
    return isinstance(session.memory_manager.long_term, PostgresLongTermMemory)


@router.get("/api/history")
async def get_history(user_id: str = "default_user", limit: int = 10):
    session = _get_user_session(user_id)
    lt = session.memory_manager.long_term
    if _is_pg(session):
        trips = await lt.get_trip_history(limit=limit)
        destinations = await lt.get_frequent_destinations(top_n=5)
        stats = await lt.get_statistics()
    else:
        trips = lt.get_trip_history(limit=limit)
        destinations = lt.get_frequent_destinations(top_n=5)
        stats = lt.get_statistics()
    return {
        "trips": trips,
        "frequent_destinations": [{"city": c, "count": n} for c, n in destinations],
        "statistics": stats,
    }


@router.get("/api/preferences")
async def get_preferences(user_id: str = "default_user"):
    session = _get_user_session(user_id)
    lt = session.memory_manager.long_term
    prefs = await lt.get_preference() if _is_pg(session) else lt.get_preference()
    return {"preferences": prefs}


@router.put("/api/preferences")
async def update_preferences(update: PreferenceUpdate, user_id: str = "default_user"):
    session = _get_user_session(user_id)
    lt = session.memory_manager.long_term
    is_pg = _is_pg(session)

    if update.action == "replace":
        if is_pg:
            await lt.save_preference(update.pref_type, update.value)
        else:
            lt.save_preference(update.pref_type, update.value)
    else:
        existing = await lt.get_preference(update.pref_type) if is_pg else lt.get_preference(update.pref_type)
        if existing:
            if isinstance(existing, list):
                existing.append(update.value)
            else:
                existing = [existing, update.value]
            if is_pg:
                await lt.save_preference(update.pref_type, existing)
            else:
                lt.save_preference(update.pref_type, existing)
        else:
            if is_pg:
                await lt.save_preference(update.pref_type, update.value)
            else:
                lt.save_preference(update.pref_type, update.value)

    prefs = await lt.get_preference() if is_pg else lt.get_preference()
    return {"preferences": prefs, "updated": update.pref_type}


@router.get("/api/context")
async def get_context(user_id: str = "default_user"):
    session = _get_user_session(user_id)
    if _is_pg(session):
        return await session.memory_manager.get_full_context_async()
    return session.memory_manager.get_full_context()


@router.get("/api/expenses")
async def get_expenses(user_id: str = "default_user", limit: int = 50):
    session = _get_user_session(user_id)
    lt = session.memory_manager.long_term
    if _is_pg(session):
        expenses = await lt.get_expenses(limit=limit)
        all_expenses = await lt.get_expenses()
    else:
        expenses = lt.get_expenses(limit=limit)
        all_expenses = lt.get_expenses()
    total = sum(e.get("amount", 0) for e in all_expenses)
    return {"expenses": expenses, "total": total, "count": len(all_expenses)}


class PluginUpdate(BaseModel):
    name: str
    enabled: bool


@router.get("/api/plugins")
async def get_plugins():
    from agents.lazy_agent_registry import LazyAgentRegistry
    registry = LazyAgentRegistry.__new__(LazyAgentRegistry)
    registry._plugin_config = registry._load_config_sync.__func__(registry)
    registry._skill_map = {}
    registry.cache = {}
    from pathlib import Path as _Path
    registry.skills_root = _Path(__file__).resolve().parent.parent.parent / "skills"
    registry._discover_skills()
    return {"plugins": registry.get_all_plugins()}


@router.put("/api/plugins")
async def update_plugin(update: PluginUpdate):
    session = session_manager.get_existing("default_user")
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    # 获取 orchestrator 的 agent_registry (LazyAgentRegistry)
    registry = session.orchestrator.agent_registry
    if not hasattr(registry, 'set_plugin_enabled'):
        raise HTTPException(status_code=400, detail="Plugin config not supported")

    if _is_pg(session):
        await registry.set_plugin_enabled_async(update.name, update.enabled)
    else:
        registry.set_plugin_enabled(update.name, update.enabled)

    # 如果禁用，清除缓存
    if not update.enabled and update.name in registry.cache:
        del registry.cache[update.name]

    return {"plugins": registry.get_all_plugins(), "updated": update.name}
