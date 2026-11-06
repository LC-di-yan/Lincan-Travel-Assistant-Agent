# -*- coding: utf-8 -*-
"""Skill ↔ AgentScope 2.x Toolkit 适配层（升级计划 P5，加法式）。

设计要点（docs/agentscope-2-upgrade-dev-plan.md §3.2 / §4.P5）：
- 不改造现有 `.claude/skills/*/script/agent.py`，13 个 Skill 保持原形态；
- 用 2.x 原生能力**追加**两层：
  1) 指令层：SKILL.md 交给 `agentscope.skill.LocalSkillLoader`（实测 13/13 原样加载）；
  2) 执行层：每个 Skill 的异步入口包装成 `FunctionTool`，注册进 `Toolkit`。
- 两个"skill"语义不同：2.x 的 Skill 是纯指令包（官方模板明确 "Skills are NOT tools"），
  本项目 Skill 是"指令 + 可执行能力"合一。本模块负责把后者投影到前者之上，
  因此**不是放弃 skill，而是让 skill 在 2.x 里既能被看见（指令）又能被调用（工具）**。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, Optional

from agents.base import SkillAgentBase
from utils.as_compat import mk_msg, msg_json, msg_text

logger = logging.getLogger(__name__)

#: 通用入参 schema：Skill 现有契约就是「一个 JSON 负载 + 一句 query」，暂不逐一手写 typed schema。
#: 后续 P5b 可为单个 Skill 提供 typed handler（如 translation(text, target_lang)），与通用桥并存。
_GENERIC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "payload": {
            "type": "object",
            "description": "交给该 Skill 的结构化输入（等同于编排器传给 Skill 的 context/previous_results）",
        }
    },
    "required": [],
}


def _make_bridge(skill_name: str, agent: SkillAgentBase):
    """把一个 Msg 契约的 Skill 包装成 FunctionTool 可调用的协程。

    实测：FunctionTool.func 返回 ToolChunk/ToolResponse 均可，但 Toolkit.call_tool
    会对非 chunk 返回值做 repr 化文本包装 —— 因此直接产出 ToolChunk（is_last=True）。
    """
    async def _bridge(payload: Optional[Dict[str, Any]] = None):
        from agentscope.message import TextBlock
        from agentscope.tool import ToolChunk

        msg = await agent.reply(mk_msg("Orchestrator", payload if payload is not None else {}, role="user"))
        data = msg_json(msg, default=None)
        if data is None:
            data = {"output": msg_text(msg)}
        return ToolChunk(
            content=[TextBlock(type="text", text=json.dumps(data, ensure_ascii=False))],
            state="success",
            is_last=True,
            metadata={"skill": skill_name},
        )

    _bridge.__name__ = f"skill_{skill_name.replace('-', '_')}"
    return _bridge


async def build_skill_toolkit(
    skills_root: str = ".claude/skills",
    agents: Optional[Dict[str, SkillAgentBase]] = None,
    names: Optional[Iterable[str]] = None,
    model: Any = None,
) -> Any:
    """构建 Toolkit：13 个 SKILL.md 作为指令 + 各 Skill 入口作为 FunctionTool。

    Args:
        skills_root: SKILL.md 根目录（默认 .claude/skills，含 13 个插件）。
        agents: {skill 目录名: BaseAgent 实例}；缺省时用 LazyAgentRegistry 按需加载。
        names: 只注册指定 skill（调试/灰度用）。

    Returns:
        agentscope.tool.Toolkit 实例（含 skill_viewer 与各 skill 工具）。
    """
    from agentscope.skill import LocalSkillLoader
    from agentscope.tool import FunctionTool, Toolkit

    wanted = set(names) if names else None
    loader = LocalSkillLoader(skills_root, scan_subdir=True)
    skills = await loader.list_skills()
    if wanted:
        skills = [s for s in skills if s.name in wanted]

    registry = None
    if agents is None:
        from agents.lazy_agent_registry import LazyAgentRegistry

        registry = LazyAgentRegistry(model=model, cache={})

    tools = []
    for skill in skills:
        name = skill.name
        agent = (agents or {}).get(name)
        if agent is None and registry is not None:
            try:
                agent = registry[name]
            except Exception as exc:  # Skill 依赖外部 key 时不应拖垮整个 Toolkit
                logger.warning("skill %s 未能加载为工具：%s", name, exc)
                agent = None
        if agent is None:
            continue
        tools.append(
            FunctionTool(
                func=_make_bridge(name, agent),
                name=name,
                description=f"{skill.description}",
                input_schema=_GENERIC_SCHEMA,
            )
        )

    logger.info("skill toolkit: %d 个指令 + %d 个工具", len(skills), len(tools))
    return Toolkit(tools=tools, skills_or_loaders=[LocalSkillLoader(skills_root, scan_subdir=True)])
