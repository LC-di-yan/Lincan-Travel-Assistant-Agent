#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Aligo 商旅助手 - CLI 交互界面
使用 Rich 库实现美观的终端交互
"""
import sys
import os

# Windows 控制台 UTF-8 编码（解决 emoji 等非 ASCII 字符的 GBK 编码报错）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        os.system("chcp 65001 >nul 2>&1")

import asyncio
from typing import Optional

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
import json

# 导入系统组件
from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG, SCENARIO_TOKENS, SYSTEM_CONFIG, RESILIENCE_CONFIG
from context.memory_manager import MemoryManager
from context.long_term_memory import PostgresLongTermMemory
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from utils.llm_resilience import retry_with_backoff, run_health_check as check_llm_health
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent


def _is_pg(memory_manager) -> bool:
    return isinstance(memory_manager.long_term, PostgresLongTermMemory)


class AligoCLI:
    """Aligo 商旅助手 CLI"""

    def __init__(self):
        """初始化 CLI"""
        self.console = Console()
        self.user_id = None
        self.session_id = None
        self.memory_manager = None
        self.orchestrator = None
        self.intention_agent = None
        self.model = None
        self._agent_cache = {}
        self.circuit_breaker = None

    def print_banner(self):
        """打印欢迎横幅"""
        self.console.print("\n[bold cyan]🌏 Aligo 商旅助手[/bold cyan] - 让差旅更简单\n", style="bold")

    def print_help(self):
        """打印帮助信息"""
        table = Table(title="命令列表", show_header=True, header_style="bold magenta")
        table.add_column("命令", style="cyan", width=20)
        table.add_column("说明", style="white")

        table.add_row("help", "显示此帮助信息")
        table.add_row("status", "查看当前状态和记忆")
        table.add_row("health", "检查 LLM 服务是否可用")
        table.add_row("clear", "清空当前任务（保留长期记忆）")
        table.add_row("history", "查看历史行程")
        table.add_row("preferences", "查看用户偏好")
        table.add_row("exit", "退出程序")
        table.add_row("", "")
        table.add_row("[自然语言]", "直接输入您的需求，如：")
        table.add_row("", "  - 我要从上海去北京出差")
        table.add_row("", "  - 北京的住宿标准是多少")
        table.add_row("", "  - 查询明天的天气")

        self.console.print(table)

    async def initialize_system(self):
        """初始化系统"""
        self.user_id = Prompt.ask("用户ID", default="default_user")

        import uuid
        self.session_id = str(uuid.uuid4())[:8]

        with self.console.status("初始化中...", spinner="dots"):
            init_agentscope()

            timeout_sec = SYSTEM_CONFIG.get("timeout", 60)
            self.model = OpenAIChatModel(
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

            # 获取数据库连接池
            from db.connection import get_pool
            db_pool = await get_pool()

            # 获取 Redis 缓存层
            from cache.connection import get_redis
            from cache.cache_layer import CacheLayer
            redis_pool = await get_redis()
            cache_layer = CacheLayer(redis_pool) if redis_pool else None

            self.memory_manager = MemoryManager(
                user_id=self.user_id,
                session_id=self.session_id,
                llm_model=self.model,
                db_pool=db_pool,
            )

            self.intention_agent = IntentionAgent(name="IntentionAgent", model=self.model)
            # 注入缓存层给 IntentionAgent
            if cache_layer is not None:
                self.intention_agent._cache_layer = cache_layer

            from agents.lazy_agent_registry import LazyAgentRegistry
            self._agent_cache = {}
            lazy_registry = LazyAgentRegistry(
                model=self.model,
                cache=self._agent_cache,
                memory_manager=self.memory_manager,
                db_pool=db_pool,
                cache_layer=cache_layer,
                user_id=self.user_id,
            )

            self.orchestrator = OrchestrationAgent(
                name="OrchestrationAgent",
                agent_registry=lazy_registry,
                memory_manager=self.memory_manager
            )

            rc = RESILIENCE_CONFIG
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=rc.get("circuit_failure_threshold", 5),
                recovery_timeout_sec=rc.get("circuit_recovery_timeout_sec", 60.0),
                half_open_successes=rc.get("circuit_half_open_successes", 2),
            )

        storage = "PostgreSQL" if _is_pg(self.memory_manager) else "JSON"
        self.console.print(f"✓ 就绪 (用户: {self.user_id}, 存储: {storage}) - 输入 help 查看帮助\n", style="green")

    async def process_query(self, user_input: str):
        """处理用户查询"""
        import time
        start_time = time.time()

        if self.circuit_breaker:
            try:
                self.circuit_breaker.raise_if_open()
            except CircuitOpenError:
                self.console.print("\n[bold yellow]⚠ 服务暂时不可用，请稍后再试。[/bold yellow]\n", style="dim")
                return

        rc = RESILIENCE_CONFIG
        max_retries = rc.get("max_retries", 3)

        # ===== 阶段1：意图识别 =====
        with self.console.status("思考中...", spinner="dots"):
            from agentscope.message import Msg

            long_term_summary = await self._get_long_term_summary(user_input)
            recent_context = self.memory_manager.short_term.get_recent_context(n_turns=5)
            context_messages = []
            if long_term_summary:
                context_messages.append(Msg(name="system", content=long_term_summary, role="system"))
            for msg in recent_context:
                context_messages.append(Msg(name=msg["role"], content=msg["content"], role=msg["role"]))
            context_messages.append(Msg(name="user", content=user_input, role="user"))

            intention_result = None
            try:
                intention_result = await retry_with_backoff(
                    lambda: self.intention_agent.reply(context_messages),
                    max_retries=max_retries,
                    base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
                    max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
                )
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()
            except CircuitOpenError:
                raise
            except Exception as e:
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()
                raise

            try:
                intention_data = json.loads(intention_result.content)
            except json.JSONDecodeError:
                self.console.print("❌ 无法理解您的需求，请重新描述", style="bold red")
                return

        intents = intention_data.get("intents", [])
        if intents:
            intent_types = [i.get("type", "") for i in intents]
            self.console.print(f"🔍 意图: {', '.join(intent_types)}", style="dim")

        # ===== 阶段2：编排执行 =====
        await self.memory_manager.add_message_async("user", user_input)

        result_queue = asyncio.Queue()
        self.orchestrator.result_queue = result_queue

        orchestration_result = None
        orchestration_error = None

        async def run_orchestrator():
            nonlocal orchestration_result
            try:
                orchestration_result = await retry_with_backoff(
                    lambda: self.orchestrator.reply(intention_result),
                    max_retries=max_retries,
                    base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
                    max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
                )
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()
            except Exception as e:
                nonlocal orchestration_error
                orchestration_error = e
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()

        task = asyncio.create_task(run_orchestrator())

        shown_agents = set()
        while not task.done():
            try:
                item = await asyncio.wait_for(result_queue.get(), timeout=5.0)
                item_type = item.get("type", "agent_result")
                agent_name = item.get("agent_name", "")

                if item_type == "agent_start":
                    display_name = self._get_agent_display_name(agent_name)
                    self.console.print(f"⏳ {display_name} ...", style="dim")
                elif item_type == "agent_result":
                    shown_agents.add(agent_name)
                    self._display_single_agent_result(item)
            except asyncio.TimeoutError:
                continue

        await task

        while not result_queue.empty():
            item = await result_queue.get()
            item_type = item.get("type", "agent_result")
            agent_name = item.get("agent_name", "")
            if item_type == "agent_result" and agent_name not in shown_agents:
                shown_agents.add(agent_name)
                self._display_single_agent_result(item)

        self.orchestrator.result_queue = None

        if orchestration_error:
            self.console.print(f"❌ 执行失败: {orchestration_error}", style="red")
            return

        try:
            result_data = json.loads(orchestration_result.content)
        except (json.JSONDecodeError, AttributeError):
            result_data = {"error": "解析结果失败"}

        elapsed = time.time() - start_time
        self.console.print(f"\n[dim]完成 ({elapsed:.1f}s)[/dim]")
        await self.memory_manager.add_message_async("assistant", json.dumps(result_data, ensure_ascii=False))

    def _display_single_agent_result(self, item: dict):
        """从队列中收到的单个 Agent 结果，即时打印"""
        agent_name = item.get("agent_name", "")
        status = item.get("status", "unknown")
        data = item.get("data", {})
        display_name = self._get_agent_display_name(agent_name)

        if status == "error":
            error_msg = data.get("error", "未知错误")
            self.console.print(f"❌ {display_name}: {error_msg}", style="red")
            return

        if status != "success":
            self.console.print(f"✓ {display_name} ({status})", style="dim")
            return

        if agent_name == "event_collection":
            origin = data.get("origin") or data.get("data", {}).get("origin")
            destination = data.get("destination") or data.get("data", {}).get("destination")
            missing = data.get("missing_info") or data.get("data", {}).get("missing_info") or []
            if destination:
                self.console.print(f"📍 {origin or '?'} → {destination}")
            if missing:
                self.console.print(f"   💡 缺少: {', '.join(missing)}", style="yellow")

        elif agent_name == "preference":
            prefs = data.get("preferences") or data.get("data", {}).get("preferences")
            if isinstance(prefs, list) and prefs:
                names = [p.get("value", "") for p in prefs if isinstance(p, dict)]
                self.console.print(f"✓ 偏好已更新: {', '.join(names)}", style="green")

        elif agent_name == "memory_query":
            answer = data.get("answer") or data.get("result") or data.get("data", {}).get("answer")
            if answer:
                self.console.print(f"📚 {answer}")

        elif agent_name == "rag_knowledge":
            answer = data.get("answer") or data.get("data", {}).get("answer")
            if answer:
                self.console.print(f"📖 {answer}")

        elif agent_name == "information_query":
            results = data.get("results") or data.get("data", {}).get("results") or {}
            summary = results.get("summary", "") if isinstance(results, dict) else ""
            if summary:
                self.console.print(f"ℹ️  {summary}")

        elif agent_name == "itinerary_planning":
            itinerary = data.get("itinerary") or data.get("data", {}).get("itinerary")
            if itinerary:
                title = itinerary.get("title", "行程规划")
                duration = itinerary.get("duration", "")
                self.console.print(f"✈️  {title} ({duration})", style="bold cyan")
                for day in itinerary.get("daily_plans", []):
                    day_num = day.get("day", 1)
                    activities = day.get("activities") or day.get("time_slots") or []
                    first = activities[0] if activities else {}
                    act = first.get("activity") or first.get("location") or ""
                    self.console.print(f"   第{day_num}天: {act} ...")
        else:
            for k in ["answer", "content", "result", "message", "summary"]:
                v = data.get(k) or data.get("data", {}).get(k) if isinstance(data.get("data"), dict) else data.get(k)
                if isinstance(v, str) and v.strip():
                    self.console.print(f"   {v}")
                    break
            else:
                self.console.print(f"✓ {display_name} 已完成", style="green")

    async def _get_long_term_summary(self, user_input: str = "") -> str:
        """生成长期记忆摘要"""
        summary_parts = []
        is_pg = _is_pg(self.memory_manager)
        lt = self.memory_manager.long_term

        # 1. 用户偏好
        prefs = await lt.get_preference() if is_pg else lt.get_preference()
        if prefs:
            pref_lines = ["【用户背景信息】（来自长期记忆，可用于推断缺失信息）"]
            for pref_key, pref_value in prefs.items():
                if pref_value:
                    if isinstance(pref_value, list):
                        pref_lines.append(f"• {pref_key}: {', '.join(pref_value)}")
                    else:
                        pref_lines.append(f"• {pref_key}: {pref_value}")
            if len(pref_lines) > 1:
                summary_parts.extend(pref_lines)

        # 2. LLM 总结历史聊天记录
        chat_summary = await self.memory_manager.get_long_term_summary_async(max_messages=50)
        if chat_summary:
            summary_parts.append("\n【历史会话总结】")
            summary_parts.append(chat_summary)

        # 3. 智能筛选相关历史行程
        all_trips = await lt.get_trip_history(limit=None) if is_pg else lt.get_trip_history(limit=None)
        if all_trips:
            relevant_trips = []
            other_trips = []
            for trip in all_trips:
                origin = trip.get("origin", "") or ""
                destination = trip.get("destination", "") or ""
                if (origin and origin in user_input) or (destination and destination in user_input):
                    relevant_trips.append(trip)
                else:
                    other_trips.append(trip)

            trips_to_show = relevant_trips[:2] + other_trips[:1]
            if trips_to_show:
                summary_parts.append("\n【历史行程】")
                for i, trip in enumerate(trips_to_show[:3], 1):
                    origin = trip.get("origin", "未知")
                    destination = trip.get("destination", "未知")
                    start_date = trip.get("start_date", "")
                    purpose = trip.get("purpose", "")
                    relevance_mark = "✦ " if trip in relevant_trips else ""
                    summary_parts.append(f"{i}. {relevance_mark}{origin} → {destination} ({start_date}) - {purpose}")

        return "\n".join(summary_parts) if summary_parts else ""

    def _get_agent_display_name(self, agent_name: str) -> str:
        """获取智能体的显示名称"""
        agent_display_names = {
            "event_collection": "事项收集",
            "preference": "偏好管理",
            "itinerary_planning": "行程规划",
            "information_query": "信息查询",
            "rag_knowledge": "知识库查询",
            "memory_query": "记忆查询",
        }
        return agent_display_names.get(agent_name, agent_name)

    async def show_status(self):
        """显示当前状态"""
        is_pg = _is_pg(self.memory_manager)
        lt = self.memory_manager.long_term

        if is_pg:
            full_context = await self.memory_manager.get_full_context_async()
        else:
            full_context = self.memory_manager.get_full_context()

        short_term_stats = full_context["short_term"]["statistics"]
        long_term_stats = full_context["long_term"]["statistics"]

        memory_table = Table(title="记忆状态", show_header=True, header_style="bold magenta")
        memory_table.add_column("类型", style="cyan")
        memory_table.add_column("状态", style="white")

        memory_table.add_row("短期记忆", f"{short_term_stats['total_messages']} 条消息")
        memory_table.add_row("长期记忆", f"{long_term_stats['total_trips']} 次行程")
        memory_table.add_row("已加载智能体", f"{len(self._agent_cache)} 个")

        self.console.print(memory_table)
        self.console.print()

        recent_messages = self.memory_manager.short_term.get_recent_context(n_turns=5)
        if recent_messages:
            dialogue_table = Table(title="最近对话 (最多5轮)", show_header=True, header_style="bold cyan")
            dialogue_table.add_column("角色", style="cyan", width=8)
            dialogue_table.add_column("内容", style="white", width=60)
            dialogue_table.add_column("时间", style="dim", width=12)

            for msg in recent_messages:
                role_name = "👤 用户" if msg["role"] == "user" else "🤖 助手"
                content = msg["content"]
                if len(content) > 100:
                    content = content[:100] + "..."
                timestamp = msg.get("timestamp", "")
                time_str = ""
                if timestamp:
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime("%H:%M:%S")
                    except:
                        pass
                dialogue_table.add_row(role_name, content, time_str)

            self.console.print(dialogue_table)
            self.console.print()

    async def run_health_check(self):
        """健康检查"""
        if self.circuit_breaker:
            status = self.circuit_breaker.get_status()
            self.console.print(f"[bold]熔断器[/bold]: {status['state']}", style="cyan")
        ok, msg = await check_llm_health(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
            model_name=LLM_CONFIG["model_name"],
            timeout_sec=RESILIENCE_CONFIG.get("health_check_timeout_sec", 10.0),
        )
        if ok:
            self.console.print("LLM 服务: [green]正常[/green]", style="bold")
        else:
            self.console.print(f"LLM 服务: [red]不可用[/red] - {msg}", style="bold")
        self.console.print()

    async def show_history(self):
        """显示历史行程"""
        is_pg = _is_pg(self.memory_manager)
        lt = self.memory_manager.long_term
        history = await lt.get_trip_history(10) if is_pg else lt.get_trip_history(10)

        if not history:
            self.console.print("暂无历史行程", style="yellow")
            return

        table = Table(title="历史行程", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan")
        table.add_column("出发地", style="white")
        table.add_column("目的地", style="white")
        table.add_column("日期", style="white")
        table.add_column("目的", style="white")

        for trip in history:
            table.add_row(
                trip.get("trip_id", ""),
                trip.get("origin", ""),
                trip.get("destination", ""),
                trip.get("start_date", ""),
                trip.get("purpose", "")
            )

        self.console.print(table)

    async def show_preferences(self):
        """显示用户偏好"""
        is_pg = _is_pg(self.memory_manager)
        lt = self.memory_manager.long_term
        prefs = await lt.get_preference() if is_pg else lt.get_preference()

        table = Table(title="用户偏好", show_header=True, header_style="bold magenta")
        table.add_column("类型", style="cyan")
        table.add_column("值", style="white")

        for key, value in prefs.items():
            if value:
                table.add_row(key, str(value))

        self.console.print(table)

    async def run(self):
        """运行 CLI"""
        self.print_banner()
        await self.initialize_system()

        while True:
            try:
                user_input = Prompt.ask("\n[cyan]>[/cyan]")
                if not user_input.strip():
                    continue

                command = user_input.strip().lower()

                if command == "exit":
                    self.memory_manager.end_session()
                    from db.connection import close_pool
                    await close_pool()
                    from cache.connection import close_redis
                    await close_redis()
                    self.console.print("再见！", style="cyan")
                    break
                elif command == "help":
                    self.print_help()
                elif command == "status":
                    await self.show_status()
                elif command == "health":
                    await self.run_health_check()
                elif command == "clear":
                    self.memory_manager.short_term.clear()
                    self.console.print("✓ 已清空短期记忆", style="green")
                elif command == "history":
                    await self.show_history()
                elif command == "preferences":
                    await self.show_preferences()
                else:
                    await self.process_query(user_input)

            except KeyboardInterrupt:
                self.console.print("\n使用 'exit' 退出", style="dim")
            except CircuitOpenError:
                self.console.print("\n[bold yellow]⚠ 服务暂时不可用，请稍后再试。[/bold yellow]", style="dim")
            except Exception as e:
                self.console.print(f"\n错误: {e}", style="red")


def run_health_check_standalone() -> int:
    """独立执行健康检查"""
    import asyncio
    init_agentscope()
    ok, msg = asyncio.run(check_llm_health(
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
        model_name=LLM_CONFIG["model_name"],
        timeout_sec=RESILIENCE_CONFIG.get("health_check_timeout_sec", 10.0),
    ))
    if ok:
        print("OK")
        return 0
    print(f"FAIL: {msg}")
    return 1


def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "health":
        exit(run_health_check_standalone())
    cli = AligoCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
