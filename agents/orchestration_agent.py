"""
协调器智能体 OrchestrationAgent
职责：根据意图识别结果，协调调度多个子智能体完成任务

核心功能：
1. 接收 IntentionAgent 的调度决策
2. 按照优先级顺序执行子智能体
3. 管理智能体之间的消息传递
4. 聚合多个智能体的结果
5. 与三层记忆系统集成

执行模式：
- Sequential (顺序执行): 按优先级依次执行，前一个的输出作为后一个的输入
- Parallel (并行执行): 同时执行多个智能体（暂不实现）
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import json
import logging
import asyncio

logger = logging.getLogger(__name__)


def _is_pg(memory_manager) -> bool:
    """判断是否使用 PostgreSQL 存储"""
    if memory_manager is None:
        return False
    from context.long_term_memory import PostgresLongTermMemory
    return isinstance(memory_manager.long_term, PostgresLongTermMemory)


class OrchestrationAgent(AgentBase):
    """协调器智能体 - 调度和协调多个子智能体"""

    def __init__(
        self,
        name: str = "OrchestrationAgent",
        agent_registry: Dict[str, AgentBase] = None,
        memory_manager = None,
        result_queue: asyncio.Queue = None,
        **kwargs
    ):
        super().__init__()
        self.name = name
        self.agent_registry = agent_registry or {}
        self.memory_manager = memory_manager
        self.result_queue = result_queue

    def register_agent(self, agent_name: str, agent: AgentBase):
        """注册子智能体"""
        self.agent_registry[agent_name] = agent
        logger.info(f"Registered agent: {agent_name}")

    def unregister_agent(self, agent_name: str):
        """注销子智能体"""
        if agent_name in self.agent_registry:
            del self.agent_registry[agent_name]
            logger.info(f"Unregistered agent: {agent_name}")

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        """
        协调执行流程

        Args:
            x: 输入消息，应包含 IntentionAgent 的输出

        Returns:
            Msg: 执行结果
        """
        if x is None:
            return Msg(
                name=self.name,
                content=json.dumps({"error": "No input provided"}),
                role="assistant"
            )

        # 解析输入
        if isinstance(x, list):
            intention_output = x[-1].content if x else "{}"
        else:
            intention_output = x.content

        # 解析意图识别结果
        try:
            intention_data = json.loads(intention_output) if isinstance(intention_output, str) else intention_output
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse intention output: {e}")
            return Msg(
                name=self.name,
                content=json.dumps({"error": "Invalid intention format"}),
                role="assistant"
            )

        # 获取智能体调度计划
        agent_schedule = intention_data.get("agent_schedule", [])
        if not agent_schedule:
            return Msg(
                name=self.name,
                content=json.dumps({
                    "status": "no_agents",
                    "message": "没有需要调度的智能体"
                }),
                role="assistant"
            )

        # 按优先级排序
        sorted_schedule = sorted(agent_schedule, key=lambda x: x.get("priority", 999))

        logger.info(f"Orchestrating {len(sorted_schedule)} agents")

        # 准备上下文信息
        context = await self._prepare_context(intention_data)

        # 并行执行智能体（按优先级分组）
        results = []
        current_priority = None
        parallel_tasks = []

        for task in sorted_schedule:
            priority = task.get("priority", 0)

            # 如果优先级变化，先执行当前批次
            if current_priority is not None and priority != current_priority:
                # 并行执行当前优先级的所有任务
                if parallel_tasks:
                    batch_results = await self._execute_parallel_agents(parallel_tasks, context, results)
                    results.extend(batch_results)
                    parallel_tasks = []

            current_priority = priority
            parallel_tasks.append(task)

        # 执行最后一批
        if parallel_tasks:
            batch_results = await self._execute_parallel_agents(parallel_tasks, context, results)
            results.extend(batch_results)

        # 聚合结果
        final_result = self._aggregate_results(results, intention_data)

        # 更新记忆
        if self.memory_manager:
            await self._update_memory(intention_data, results)

        return Msg(
            name=self.name,
            content=json.dumps(final_result, ensure_ascii=False),
            role="assistant"
        )

    async def _prepare_context(self, intention_data: Dict[str, Any]) -> Dict[str, Any]:
        """准备上下文信息，供子智能体使用"""
        context = {
            "reasoning": intention_data.get("reasoning", ""),
            "intents": intention_data.get("intents", []),
            "key_entities": intention_data.get("key_entities", {}),
            "rewritten_query": intention_data.get("rewritten_query", "")
        }

        # 快速路由提取的参数（如记账金额、分类等）
        if "fast_expense" in intention_data:
            context["fast_expense"] = intention_data["fast_expense"]
        if "fast_train_ticket" in intention_data:
            context["fast_train_ticket"] = intention_data["fast_train_ticket"]
        if "fast_currency" in intention_data:
            context["fast_currency"] = intention_data["fast_currency"]

        # 从记忆系统获取上下文
        if self.memory_manager:
            recent_context = self.memory_manager.short_term.get_recent_context(3)
            context["recent_dialogue"] = recent_context

            lt = self.memory_manager.long_term
            if _is_pg(self.memory_manager):
                preferences = await lt.get_preference()
            else:
                preferences = lt.get_preference()
            context["user_preferences"] = preferences

        return context

    async def _execute_parallel_agents(
        self,
        tasks: List[Dict],
        context: Dict[str, Any],
        previous_results: List[Dict]
    ) -> List[Dict]:
        """
        并行执行多个智能体
        """
        if not tasks:
            return []

        # 如果只有一个任务，直接执行
        if len(tasks) == 1:
            task = tasks[0]
            agent_name = task.get("agent_name")

            # 推送 start 事件
            if self.result_queue is not None:
                await self.result_queue.put({
                    "type": "agent_start",
                    "agent_name": agent_name,
                    "status": "running",
                })

            result = await self._execute_agent(
                agent_name=agent_name,
                context=context,
                reason=task.get("reason", ""),
                expected_output=task.get("expected_output", ""),
                previous_results=previous_results
            )
            if self.result_queue is not None:
                await self.result_queue.put({
                    "type": "agent_result",
                    "agent_name": agent_name,
                    "status": result.get("status", "unknown"),
                    "data": result.get("data", {}),
                })
            return [{
                "agent_name": agent_name,
                "priority": task.get("priority", 0),
                "result": result
            }]

        # 多个任务并行执行，每个 Agent 完成后立即推送结果到队列
        logger.info(f"Executing {len(tasks)} agents in parallel")

        async def _run_and_push(agent_name: str, priority: int, coroutine):
            """包装单个 Agent 执行，完成后立即推送到 result_queue"""
            if self.result_queue is not None:
                await self.result_queue.put({
                    "type": "agent_start",
                    "agent_name": agent_name,
                    "status": "running",
                })

            try:
                result = await coroutine
            except Exception as e:
                logger.error(f"Parallel agent execution failed: {agent_name}, error: {e}")
                result = {
                    "status": "error",
                    "agent_name": agent_name,
                    "data": {"error": str(e)},
                    "message": f"并行执行失败: {str(e)}"
                }

            if self.result_queue is not None:
                await self.result_queue.put({
                    "type": "agent_result",
                    "agent_name": agent_name,
                    "status": result.get("status", "unknown"),
                    "data": result.get("data", {}),
                })

            return {"agent_name": agent_name, "priority": priority, "result": result}

        # 创建包装协程
        wrapped_coroutines = []
        for task in tasks:
            agent_name = task.get("agent_name")
            priority = task.get("priority", 0)
            logger.info(f"Parallel executing agent: {agent_name} (priority={priority})")

            coroutine = self._execute_agent(
                agent_name=agent_name,
                context=context,
                reason=task.get("reason", ""),
                expected_output=task.get("expected_output", ""),
                previous_results=previous_results
            )
            wrapped_coroutines.append(_run_and_push(agent_name, priority, coroutine))

        # 并行执行，每个完成后立即推送
        results = await asyncio.gather(*wrapped_coroutines, return_exceptions=True)

        # gather 不应再抛异常（已在 wrapper 中处理），但做防御性处理
        final_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Unexpected gather exception: {r}")
                continue
            final_results.append(r)

        return final_results

    async def _execute_agent(
        self,
        agent_name: str,
        context: Dict[str, Any],
        reason: str,
        expected_output: str,
        previous_results: List[Dict]
    ) -> Dict[str, Any]:
        """
        执行单个智能体
        """
        # 检查智能体是否注册
        if agent_name not in self.agent_registry:
            logger.warning(f"Agent not registered: {agent_name}")
            return {
                "status": "error",
                "message": f"智能体未注册: {agent_name}"
            }

        agent = self.agent_registry[agent_name]

        # 构建输入消息
        input_data = {
            "context": context,
            "reason": reason,
            "expected_output": expected_output,
            "previous_results": previous_results
        }
        # 传递快速路由提取的参数
        if "fast_expense" in context:
            input_data["fast_expense"] = context["fast_expense"]
        if "fast_train_ticket" in context:
            input_data["fast_train_ticket"] = context["fast_train_ticket"]
        if "fast_currency" in context:
            input_data["fast_currency"] = context["fast_currency"]

        input_msg = Msg(
            name="Orchestrator",
            content=json.dumps(input_data, ensure_ascii=False),
            role="user"
        )

        try:
            # 调用智能体
            import time as _time
            _t0 = _time.monotonic()
            response = await agent.reply(input_msg)
            _t_agent = (_time.monotonic() - _t0) * 1000
            _msg = f"[TIMING] Agent '{agent_name}' reply took {_t_agent:.0f}ms"
            logger.info(_msg)
            print(_msg, flush=True)

            # 解析响应
            if isinstance(response.content, str):
                try:
                    result = json.loads(response.content)
                except json.JSONDecodeError:
                    result = {"output": response.content}
            else:
                result = response.content

            # 检查 result 中是否有 error 字段
            if isinstance(result, dict) and "error" in result:
                error_msg = result.get("error", "未知错误")
                return {
                    "status": "error",
                    "agent_name": agent_name,
                    "data": result,
                    "message": error_msg
                }

            return {
                "status": "success",
                "agent_name": agent_name,
                "data": result
            }

        except Exception as e:
            logger.error(f"Agent execution failed: {agent_name}, error: {e}")
            return {
                "status": "error",
                "agent_name": agent_name,
                "data": {"error": str(e)},
                "message": f"智能体执行失败: {str(e)}"
            }

    def _aggregate_results(
        self,
        results: List[Dict],
        intention_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """聚合多个智能体的结果"""
        aggregated = {
            "status": "completed",
            "intention": {
                "intents": intention_data.get("intents", []),
                "key_entities": intention_data.get("key_entities", {})
            },
            "agents_executed": len(results),
            "results": []
        }

        for result in results:
            aggregated["results"].append({
                "agent_name": result["agent_name"],
                "priority": result["priority"],
                "status": result["result"].get("status", "unknown"),
                "data": result["result"].get("data", {})
            })

        errors = [r for r in results if r["result"].get("status") == "error"]
        if errors:
            aggregated["status"] = "partial_failure"
            aggregated["errors"] = len(errors)

        return aggregated

    async def _update_memory(self, intention_data: Dict[str, Any], results: List[Dict]):
        """更新记忆系统"""
        if not self.memory_manager:
            return

        is_pg = _is_pg(self.memory_manager)
        lt = self.memory_manager.long_term

        for result in results:
            agent_name = result["agent_name"]
            data = result["result"].get("data", {})

            # 如果是偏好智能体，保存偏好信息到长期记忆
            if agent_name == "preference" and isinstance(data, dict):
                preferences_data = data.get("preferences", {})

                # 新格式：preferences 是列表，包含 {type, value, action}
                if isinstance(preferences_data, list):
                    for pref_item in preferences_data:
                        if not isinstance(pref_item, dict):
                            continue

                        pref_type = pref_item.get("type")
                        pref_value = pref_item.get("value")
                        pref_action = pref_item.get("action", "replace")

                        if not pref_type or not pref_value:
                            continue

                        if pref_action == "append":
                            if is_pg:
                                current_prefs = await lt.get_preference()
                            else:
                                current_prefs = lt.get_preference()
                            existing_value = current_prefs.get(pref_type)

                            if isinstance(existing_value, list):
                                if pref_value not in existing_value:
                                    existing_value.append(pref_value)
                            else:
                                existing_value = [existing_value, pref_value] if existing_value else [pref_value]

                            if is_pg:
                                await lt.save_preference(pref_type, existing_value)
                            else:
                                lt.save_preference(pref_type, existing_value)
                            logger.info(f"Appended to {pref_type}: {pref_value}")
                        else:
                            if is_pg:
                                await lt.save_preference(pref_type, pref_value)
                            else:
                                lt.save_preference(pref_type, pref_value)
                            logger.info(f"Replaced {pref_type}: {pref_value}")

                # 旧格式兼容
                elif isinstance(preferences_data, dict):
                    for pref_type, value in preferences_data.items():
                        if value and pref_type != "has_preferences" and pref_type != "error":
                            if is_pg:
                                await lt.save_preference(pref_type, value)
                            else:
                                lt.save_preference(pref_type, value)
                            logger.info(f"Updated {pref_type}: {value} (legacy format)")

            # 如果是行程规划智能体，保存行程到长期记忆
            if agent_name == "itinerary_planning" and isinstance(data, dict):
                itinerary = data.get("itinerary", {})

                if itinerary:
                    event_data = {}
                    for r in results:
                        if r["agent_name"] == "event_collection":
                            event_data = r["result"].get("data", {})
                            break

                    origin = event_data.get("origin")
                    destination = event_data.get("destination")
                    start_date = event_data.get("start_date")
                    end_date = event_data.get("end_date")
                    purpose = event_data.get("trip_purpose", "旅游")

                    if destination:
                        trip_info = {
                            "origin": origin,
                            "destination": destination,
                            "start_date": start_date,
                            "end_date": end_date,
                            "purpose": purpose
                        }
                        if is_pg:
                            await lt.save_trip_history(trip_info)
                        else:
                            lt.save_trip_history(trip_info)
                        logger.info(f"Saved trip to long-term memory: {origin} -> {destination}")

        logger.info("Memory updated after orchestration")
