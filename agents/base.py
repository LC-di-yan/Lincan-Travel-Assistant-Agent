# -*- coding: utf-8 -*-
"""项目自有 Agent 基类 —— 取代 agentscope.agent.AgentBase（2.x 已删除）。

docs/agentscope-2-upgrade-dev-plan.md §4.P4：
全项目唯一定义；约定与 1.x AgentBase 完全一致（__call__ -> await reply），
Skills 与核心 Agent 均继承此类，不再 import 框架的基类。
"""
from __future__ import annotations

from typing import Any, Optional


class SkillAgentBase:
    """最小基类：统一调用约定（await agent(x) == await agent.reply(x)）。

    子类必须实现 async reply(self, x) -> Msg。
    """

    def __init__(self, name: str = "", **kwargs: Any) -> None:
        # 兼容 1.x 时代 super().__init__() 无参调用
        self.name = name or self.__class__.__name__

    async def __call__(self, x: Any = None, **kwargs: Any):
        return await self.reply(x, **kwargs)

    async def reply(self, x: Any = None, **kwargs: Any):
        raise NotImplementedError("SkillAgentBase subclasses must implement async reply()")
