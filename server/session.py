"""用户会话管理 — 按用户 ID 缓存 Agent 实例"""
import asyncio
import os
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from agentscope.model import OpenAIChatModel
from config import LLM_CONFIG, LLM_FALLBACKS, SYSTEM_CONFIG, RESILIENCE_CONFIG
from config_agentscope import init_agentscope
from context.memory_manager import MemoryManager
from context.session_focus_state import SessionFocusState
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent
from agents.lazy_agent_registry import LazyAgentRegistry
from utils.circuit_breaker import CircuitBreaker
from utils.llm_failover import build_chat_model
from utils.json_store import validate_user_id
from utils.trip_request import TripRequest
from server.personal.models import Event, PlanRef

logger = logging.getLogger(__name__)

def _configured_max_sessions() -> int:
    try:
        value = int(os.environ.get("ALIGO_MAX_SESSIONS", "50"))
    except ValueError:
        raise ValueError("ALIGO_MAX_SESSIONS 必须是大于 0 的整数") from None
    if value < 1:
        raise ValueError("ALIGO_MAX_SESSIONS 必须是大于 0 的整数")
    return value


MAX_SESSIONS = _configured_max_sessions()


@dataclass
class UserSession:
    user_id: str
    session_id: str
    memory_manager: MemoryManager
    intention_agent: IntentionAgent
    orchestrator: OrchestrationAgent
    circuit_breaker: CircuitBreaker
    model: OpenAIChatModel
    last_active: float = field(default_factory=time.monotonic)
    long_term_summary: str = ""
    messages_since_summary: int = 0
    pending_intention: Optional[Dict] = field(default=None)  # 等待用户澄清的意图数据
    pending_since: float = 0.0  # pending_intention 的创建时刻(monotonic)，用于超时失效
    focus_state: SessionFocusState = field(default_factory=SessionFocusState)
    # 同一会话的对话请求串行执行：编排器的 result_queue / pending_intention 都是
    # 会话级共享状态，两条并发请求会互相覆盖，表现为其中一条静默返回空结果。
    chat_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    trip_request: TripRequest | None = None
    trip_original: str = ""
    trip_options: list[dict] = field(default_factory=list)
    trip_selection: str | None = None
    trip_plan_ref: PlanRef | None = None
    trip_plan_revision: int | None = None
    trip_carry_items: list[Event] = field(default_factory=list)


class SessionManager:
    """管理每个用户的 Agent 实例和 MemoryManager，避免重复创建"""

    def __init__(self):
        self._sessions: Dict[str, UserSession] = {}
        self._initialized = False
        self._pool = None
        self._cache_layer = None
        self._init_lock = asyncio.Lock()

    async def _ensure_init(self):
        async with self._init_lock:
            if not self._initialized:
                init_agentscope()
                from db.connection import get_pool
                self._pool = await get_pool()
                from cache.connection import get_redis
                from cache.cache_layer import CacheLayer
                self._redis_pool = await get_redis()
                self._cache_layer = CacheLayer(self._redis_pool) if self._redis_pool else None
                self._initialized = True

    def _evict_if_needed(self):
        if len(self._sessions) < MAX_SESSIONS:
            return
        idle = [key for key, session in self._sessions.items() if not session.chat_lock.locked()]
        if not idle:
            raise RuntimeError("当前会话较多，请稍后再试")
        oldest_key = min(idle, key=lambda k: self._sessions[k].last_active)
        logger.info(f"Evicting stale session for user {oldest_key}")
        del self._sessions[oldest_key]

    def _touch(self, cache_key: str) -> UserSession:
        # Dict order breaks equal clock ticks and tracks explicit access, not just creation.
        session = self._sessions.pop(cache_key)
        session.last_active = time.monotonic()
        self._sessions[cache_key] = session
        return session

    async def get_or_create(self, user_id: str, session_id: Optional[str] = None) -> UserSession:
        validate_user_id(user_id)
        await self._ensure_init()

        if session_id is None:
            # 客户端没带 session_id 时复用该用户最近的会话。
            # 以前每次新建：① 短期记忆（10 轮上下文）在两条消息之间直接丢失；
            # ② 一个用户堆出多个 LongTermMemory 实例，读接口拿到最老那个的
            #    陈旧快照，页面侧栏的偏好/费用永远是空的。
            existing = self.get_existing(user_id)
            if existing is not None:
                return await self.get_or_create(user_id, existing.session_id)
            session_id = str(uuid.uuid4())[:8]

        cache_key = f"{user_id}:{session_id}"
        if cache_key in self._sessions:
            session = self._touch(cache_key)
            await session.orchestrator.agent_registry.refresh_config()
            return session

        self._evict_if_needed()

        timeout_sec = SYSTEM_CONFIG.get("timeout", 60)
        model = build_chat_model(LLM_CONFIG, LLM_FALLBACKS, timeout=float(timeout_sec))

        memory_manager = MemoryManager(
            user_id=user_id,
            session_id=session_id,
            llm_model=model,
            db_pool=self._pool,
        )

        intention_agent = IntentionAgent(name="IntentionAgent", model=model)
        # 注入缓存层给 IntentionAgent
        if self._cache_layer is not None:
            intention_agent._cache_layer = self._cache_layer

        agent_cache: Dict = {}
        lazy_registry = LazyAgentRegistry(
            model=model,
            cache=agent_cache,
            memory_manager=memory_manager,
            db_pool=self._pool,
            cache_layer=self._cache_layer,
            user_id=user_id,
        )

        orchestrator = OrchestrationAgent(
            name="OrchestrationAgent",
            agent_registry=lazy_registry,
            memory_manager=memory_manager,
        )

        rc = RESILIENCE_CONFIG
        circuit_breaker = CircuitBreaker(
            failure_threshold=rc.get("circuit_failure_threshold", 5),
            recovery_timeout_sec=rc.get("circuit_recovery_timeout_sec", 60.0),
            half_open_successes=rc.get("circuit_half_open_successes", 2),
        )

        session = UserSession(
            user_id=user_id,
            session_id=session_id,
            memory_manager=memory_manager,
            intention_agent=intention_agent,
            orchestrator=orchestrator,
            circuit_breaker=circuit_breaker,
            model=model,
            focus_state=SessionFocusState(),
        )

        # 先发布再等待配置加载，避免首次并发请求构造同一会话的两个实例。
        self._sessions[cache_key] = session
        self._touch(cache_key)
        try:
            await lazy_registry.refresh_config()
        except Exception:
            self._sessions.pop(cache_key, None)
            raise
        logger.info(f"Created session for user {user_id} (session {session_id})")
        return session

    def get_existing(self, user_id: str) -> Optional[UserSession]:
        """取该用户最近活跃的会话（以前取字典里第一个，可能是个空壳）。"""
        candidates = [key for key, session in reversed(self._sessions.items()) if session.user_id == user_id]
        if not candidates:
            return None
        return self._touch(max(candidates, key=lambda key: self._sessions[key].last_active))

    async def new_session(self, user_id: str) -> UserSession:
        return await self.get_or_create(user_id, uuid.uuid4().hex[:16])


session_manager = SessionManager()
