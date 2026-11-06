"""
Aligo Multi-Agent System - Agents Package

PEP 562 懒加载（升级计划 §3.1）：Skill 只需要 agents.base.SkillAgentBase，
不应在 import agents.base 时连带拉起 intention/orchestration 编排层
（它们各自还要引入 LLM、决策层、缓存等重依赖）。
"""
from typing import Any

_LAZY = {
    "IntentionAgent": ("agents.intention_agent", "IntentionAgent"),
    "OrchestrationAgent": ("agents.orchestration_agent", "OrchestrationAgent"),
    "LazyAgentRegistry": ("agents.lazy_agent_registry", "LazyAgentRegistry"),
}

__all__ = [
    "SkillAgentBase",
    "IntentionAgent",
    "OrchestrationAgent",
    "LazyAgentRegistry",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        import importlib

        module_name, attr = _LAZY[name]
        value = getattr(importlib.import_module(module_name), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'agents' has no attribute {name!r}")
