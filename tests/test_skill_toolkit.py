# -*- coding: utf-8 -*-
"""Skill ↔ Toolkit 适配层测试（升级计划 P5，加法式）。

验证三件事：
1. 13 个 SKILL.md 被 2.x 原生 LocalSkillLoader 装载为「指令层」（整库，不做名过滤）；
2. 现有 Skill（Msg 契约）被投影成 FunctionTool（工具层可按名过滤）；
3. Toolkit.call_tool 的最终 ToolResponse 能拿到 Skill 的 JSON 结果。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.base import SkillAgentBase  # noqa: E402
from agents.skill_toolkit import build_skill_toolkit  # noqa: E402
from utils.as_compat import mk_msg, msg_json  # noqa: E402


class _FakeSkill(SkillAgentBase):
    """不走网络的假 Skill：回显 payload，用于验证桥接契约。"""

    def __init__(self, name="translation", **kw):
        super().__init__(name=name, **kw)

    async def reply(self, x=None, **kwargs):
        data = msg_json(x, default={})
        return mk_msg(self.name, {"ok": True, "echo": data, "skill": self.name})


def test_toolkit_registers_skill_as_tool():
    async def run():
        tk = await build_skill_toolkit(names=["translation"], agents={"translation": _FakeSkill()})
        return await tk.get_tool("translation")

    tool = asyncio.run(run())
    assert tool is not None, "Skill 应可作为工具被 Toolkit 检索到"
    assert tool.name == "translation"


def test_toolkit_loads_skill_instructions():
    """指令层 = 整个 .claude/skills 库（13 个），工具层才按 names 过滤。"""
    async def run():
        tk = await build_skill_toolkit(names=["translation"], agents={"translation": _FakeSkill()})
        return await tk._get_available_skills()

    skills = asyncio.run(run())
    assert len(skills) == 13, f"指令层应装载全部 13 个 SKILL.md，实际 {len(skills)}"


def test_all_13_skill_markdown_loadable():
    from agentscope.skill import LocalSkillLoader

    async def run():
        return await LocalSkillLoader(".claude/skills", scan_subdir=True).list_skills()

    skills = asyncio.run(run())
    assert len(skills) == 13, f"期望 13 个 skill，实际 {len(skills)}"
    assert all(s.name and s.description for s in skills)


def test_bridge_roundtrip_returns_json():
    async def run():
        from agentscope.message import ToolCallBlock
        from agentscope.state import AgentState

        tk = await build_skill_toolkit(names=["translation"], agents={"translation": _FakeSkill()})
        call = ToolCallBlock(
            type="tool_call",
            id="call-1",
            name="translation",
            input=json.dumps({"payload": {"text": "hello", "target": "zh"}}),
        )
        state = AgentState(session_id="test-session")
        last = None
        async for item in tk.call_tool(call, state):
            last = item          # 流的最后一帧是框架的最终 ToolResponse
        return last

    last = asyncio.run(run())
    assert last is not None and type(last).__name__ == "ToolResponse"
    text = "".join(getattr(b, "text", "") or "" for b in (last.content or []))
    data = json.loads(text)
    assert data["ok"] is True
    # FunctionTool 把 input 的键展开成 kwargs：payload 即 Skill 收到的结构化输入
    assert data["echo"]["text"] == "hello"
    assert data["skill"] == "translation"
