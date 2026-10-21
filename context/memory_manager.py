"""
记忆管理器 (Memory Manager)
统一管理两层记忆，提供简单的API
"""
from typing import Dict, Any, List, Optional
from .short_term_memory import ShortTermMemory
from .long_term_memory import LongTermMemory, PostgresLongTermMemory
import logging
import json

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    记忆管理器：统一管理两层记忆
    - 短期记忆：最近对话（会话级）
    - 长期记忆：用户偏好和历史（跨会话）
    """

    def __init__(self, user_id: str, session_id: str, storage_path: str = "data/memory", llm_model=None, db_pool=None):
        self.user_id = user_id
        self.session_id = session_id
        self.llm_model = llm_model

        # 初始化两层记忆
        self.short_term = ShortTermMemory(max_turns=10)
        if db_pool:
            self.long_term = PostgresLongTermMemory(user_id, db_pool)
        else:
            self.long_term = LongTermMemory(user_id, storage_path)

        logger.info(f"Memory manager initialized for user {user_id}, session {session_id}")

    # ========== 短期记忆操作 ==========

    def add_message(self, role: str, content: str, metadata: Dict = None):
        """添加消息到短期记忆和长期记忆"""
        self.short_term.add_message(role, content, metadata)
        self.long_term.add_chat_message(role, content, self.session_id)

    async def add_message_async(self, role: str, content: str, metadata: Dict = None):
        """异步添加消息（PG 模式使用，JSON 模式自动降级为同步）"""
        self.short_term.add_message(role, content, metadata)
        result = self.long_term.add_chat_message(role, content, self.session_id)
        if hasattr(result, '__await__'):
            await result

    # ========== 综合查询 ==========

    def get_full_context(self) -> Dict[str, Any]:
        """获取完整上下文（同步版本，JSON 模式用）"""
        return {
            "short_term": {
                "recent_dialogue": self.short_term.get_recent_context(5),
                "context_string": self.short_term.get_context_string(5),
                "statistics": self.short_term.get_statistics()
            },
            "long_term": {
                "preferences": self.long_term.get_preference(),
                "chat_history": self.long_term.get_chat_history(10),
                "trip_history": self.long_term.get_trip_history(5),
                "frequent_destinations": self.long_term.get_frequent_destinations(3),
                "statistics": self.long_term.get_statistics()
            }
        }

    @staticmethod
    async def _maybe_await(method, *args, **kwargs):
        """调用方法，如果是协程则 await，否则直接返回"""
        result = method(*args, **kwargs)
        if hasattr(result, '__await__'):
            return await result
        return result

    async def get_full_context_async(self) -> Dict[str, Any]:
        """获取完整上下文（异步版本，PG 模式用，JSON 模式自动降级）"""
        return {
            "short_term": {
                "recent_dialogue": self.short_term.get_recent_context(5),
                "context_string": self.short_term.get_context_string(5),
                "statistics": self.short_term.get_statistics()
            },
            "long_term": {
                "preferences": await self._maybe_await(self.long_term.get_preference),
                "chat_history": await self._maybe_await(self.long_term.get_chat_history, 10),
                "trip_history": await self._maybe_await(self.long_term.get_trip_history, 5),
                "frequent_destinations": await self._maybe_await(self.long_term.get_frequent_destinations, 3),
                "statistics": await self._maybe_await(self.long_term.get_statistics)
            }
        }

    def get_context_for_agent(self, long_term_summary: str = None) -> str:
        """获取用于Agent的上下文字符串（同步版本）"""
        lines = []

        if long_term_summary:
            lines.append("【历史会话总结】")
            lines.append(long_term_summary)
            lines.append("")

        prefs = self.long_term.get_preference()
        has_prefs = any(v for v in prefs.values() if v)
        if has_prefs:
            lines.append("【用户偏好】")
            for key, value in prefs.items():
                if value:
                    lines.append(f"- {key}: {value}")
            lines.append("")

        context_str = self.short_term.get_context_string(3)
        if context_str != "无历史对话":
            lines.append("【当前会话对话】")
            lines.append(context_str)
            lines.append("")

        return "\n".join(lines) if lines else "无上下文信息"

    async def get_context_for_agent_async(self, long_term_summary: str = None) -> str:
        """获取用于Agent的上下文字符串（异步版本）"""
        lines = []

        if long_term_summary:
            lines.append("【历史会话总结】")
            lines.append(long_term_summary)
            lines.append("")

        prefs = await self._maybe_await(self.long_term.get_preference)
        has_prefs = any(v for v in prefs.values() if v)
        if has_prefs:
            lines.append("【用户偏好】")
            for key, value in prefs.items():
                if value:
                    lines.append(f"- {key}: {value}")
            lines.append("")

        context_str = self.short_term.get_context_string(3)
        if context_str != "无历史对话":
            lines.append("【当前会话对话】")
            lines.append(context_str)
            lines.append("")

        return "\n".join(lines) if lines else "无上下文信息"

    # ========== 会话管理 ==========

    def end_session(self):
        """结束会话"""
        self.short_term.clear()
        logger.info(f"Session ended: {self.session_id}")

    async def get_long_term_summary_async(self, max_messages: int = 50) -> str:
        """使用LLM总结长期聊天历史"""
        if not self.llm_model:
            return ""

        all_history = await self._get_history_for_summary(max_messages)
        history_from_other_sessions = [
            msg for msg in all_history
            if msg.get("session_id") != self.session_id
        ]

        trip_history = await self._get_trips_for_summary()

        if not history_from_other_sessions and not trip_history:
            return ""

        # 构建聊天记录文本
        history_text = []
        for msg in history_from_other_sessions[-max_messages:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            history_text.append(f"[{timestamp}] {role}: {content}")

        history_str = "\n".join(history_text) if history_text else "（无聊天记录）"

        # 构建行程历史文本
        trip_text = []
        for trip in trip_history:
            origin = trip.get("origin", "未知")
            destination = trip.get("destination", "未知")
            start_date = trip.get("start_date", "")
            end_date = trip.get("end_date", "")
            purpose = trip.get("purpose", "旅游")
            timestamp = trip.get("timestamp", "")

            if start_date and end_date:
                trip_text.append(f"[{timestamp}] {origin} → {destination} ({start_date} 至 {end_date}) - {purpose}")
            elif start_date:
                trip_text.append(f"[{timestamp}] {origin} → {destination} ({start_date}) - {purpose}")
            else:
                trip_text.append(f"[{timestamp}] {origin} → {destination} - {purpose}")

        trip_str = "\n".join(trip_text) if trip_text else "（无行程记录）"

        summarization_prompt = f"""请总结以下历史信息中的关键内容，包括：
1. 用户的旅行偏好和习惯
2. 用户询问过的重要问题
3. 用户的出行历史和目的地
4. 其他重要的上下文信息

【历史聊天记录】
{history_str}

【历史行程记录】
{trip_str}

请用简洁的语言总结（不超过200字）："""

        try:
            response = await self.llm_model([{"role": "user", "content": summarization_prompt}])

            def _safe_hasattr(obj, attr):
                try:
                    return hasattr(obj, attr)
                except (KeyError, AttributeError, TypeError):
                    return False

            summary = ""
            is_async_iterable = False
            try:
                is_async_iterable = hasattr(response, '__aiter__')
            except (KeyError, AttributeError, TypeError):
                pass
            if is_async_iterable:
                async for chunk in response:
                    if isinstance(chunk, str):
                        summary = chunk
                    elif _safe_hasattr(chunk, 'content'):
                        if isinstance(chunk.content, str):
                            summary = chunk.content
                        elif isinstance(chunk.content, list):
                            for item in chunk.content:
                                if isinstance(item, dict) and item.get('type') == 'text':
                                    summary = item.get('text', '')
            elif _safe_hasattr(response, 'content'):
                summary = str(response.content)
            else:
                summary = str(response)

            logger.info(f"Generated long-term memory summary ({len(summary)} chars)")
            return summary.strip()

        except Exception as e:
            logger.error(f"Failed to generate long-term summary: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return ""

    async def _get_history_for_summary(self, max_messages: int) -> list:
        """获取聊天历史（兼容同步/异步 long_term）"""
        result = self.long_term.get_chat_history(limit=max_messages)
        if hasattr(result, '__await__'):
            return await result
        return result

    async def _get_trips_for_summary(self) -> list:
        """获取行程历史（兼容同步/异步 long_term）"""
        result = self.long_term.get_trip_history(limit=20)
        if hasattr(result, '__await__'):
            return await result
        return result

    def get_long_term_summary(self, max_messages: int = 50) -> str:
        """同步版本（仅用于 JSON 模式）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            logger.warning("get_long_term_summary called from async context, use get_long_term_summary_async instead")
            return ""
        except RuntimeError:
            return asyncio.run(self.get_long_term_summary_async(max_messages))
