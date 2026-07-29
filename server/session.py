"""用户会话管理 — 按用户 ID 缓存 Agent 实例"""
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from agentscope.model import OpenAIChatModel
from config import LLM_CONFIG, SYSTEM_CONFIG, RESILIENCE_CONFIG
from config_agentscope import init_agentscope
from context.memory_manager import MemoryManager
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent
from agents.lazy_agent_registry import LazyAgentRegistry
from utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

MAX_SESSIONS = 50


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


class SessionManager:
    """管理每个用户的 Agent 实例和 MemoryManager，避免重复创建"""

    def __init__(self):
        self._sessions: Dict[str, UserSession] = {}
        self._initialized = False
        self._pool = None

    async def _ensure_init(self):
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
        oldest_key = min(self._sessions, key=lambda k: self._sessions[k].last_active)
        logger.info(f"Evicting stale session for user {oldest_key}")
        del self._sessions[oldest_key]

    async def get_or_create(self, user_id: str, session_id: Optional[str] = None) -> UserSession:
        await self._ensure_init()

        if session_id is None:
            session_id = str(uuid.uuid4())[:8]

        cache_key = f"{user_id}:{session_id}"
        if cache_key in self._sessions:
            session = self._sessions[cache_key]
            session.last_active = time.monotonic()
            return session

        self._evict_if_needed()

        timeout_sec = SYSTEM_CONFIG.get("timeout", 60)
        model = OpenAIChatModel(
            model_name=LLM_CONFIG["model_name"],
            api_key=LLM_CONFIG["api_key"],
            stream=False,
            client_kwargs={
                "base_url": LLM_CONFIG["base_url"],
                "timeout": float(timeout_sec),
            },
            generate_kwargs={
                "temperature": LLM_CONFIG.get("temperature", 0.7),
                "max_tokens": LLM_CONFIG.get("max_tokens", 2000),
            },
        )

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
        )

        self._sessions[cache_key] = session
        logger.info(f"Created session for user {user_id} (session {session_id})")
        return session

    def get_existing(self, user_id: str) -> Optional[UserSession]:
        for session in self._sessions.values():
            if session.user_id == user_id:
                session.last_active = time.monotonic()
                return session
        return None

    async def new_session(self, user_id: str) -> UserSession:
        self._sessions = {k: v for k, v in self._sessions.items() if v.user_id != user_id}
        return await self.get_or_create(user_id)


session_manager = SessionManager()
