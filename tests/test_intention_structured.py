# -*- coding: utf-8 -*-
"""意图识别结构化输出测试（P6a）：tool_call 通道优先，文本解析兜底。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.intention_agent import IntentionAgent  # noqa: E402
from agentscope.message import ToolCallBlock  # noqa: E402
from utils.as_compat import mk_msg  # noqa: E402


class _StructuredModel:
    """返回 tool_call 块的假模型（模拟 submit_intent 强制工具调用）。"""

    def __init__(self, payload, name="submit_intent"):
        self.payload = payload
        self.name = name
        self.call_count = 0
        self.last_kwargs = None

    async def __call__(self, messages, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs

        class _Resp:
            content = [
                ToolCallBlock(
                    type="tool_call",
                    id="call-structured-1",
                    name=self.name,
                    input=json.dumps(self.payload, ensure_ascii=False),
                )
            ]

        return _Resp()


class _TextModel:
    """返回纯文本（带 markdown 围栏）的假模型，用于验证兜底路径。"""

    def __init__(self, text):
        self.text = text
        self.call_count = 0

    async def __call__(self, messages, **kwargs):
        self.call_count += 1

        class _Resp:
            def __init__(self, text):
                self.content = text

        return _Resp(self.text)


def _agent(model):
    agent = IntentionAgent(name="TestAgent", model=model)
    from unittest.mock import MagicMock

    agent.skill_loader = MagicMock()
    agent.skill_loader.get_skill_prompt.return_value = "mock skills"
    return agent


def test_structured_tool_call_is_preferred():
    payload = {
        "reasoning": "结构化通道",
        "intents": [{"type": "hotel_search", "confidence": 0.9}],
        "key_entities": {"city": "杭州"},
        "rewritten_query": "杭州酒店",
        "needs_clarification": False,
        "agent_schedule": [{"agent_name": "hotel_search", "priority": 1}],
    }
    model = _StructuredModel(payload)
    result = asyncio.run(_agent(model).reply(mk_msg("user", "杭州酒店", role="user")))
    from utils.as_compat import msg_json

    data = msg_json(result, default={})
    assert data["intents"][0]["type"] == "hotel_search"
    assert data["key_entities"]["city"] == "杭州"
    # 结构化模式应把 tools/tool_choice 传给模型
    assert model.last_kwargs.get("tools"), "应传入 submit_intent 工具 schema"
    assert model.last_kwargs.get("tool_choice") is not None


def test_text_fallback_when_no_tool_call():
    model = _TextModel('\u0060\u0060\u0060json\n{"intents": [{"type": "preference"}], "reasoning": "文本兜底"}\n\u0060\u0060\u0060')
    result = asyncio.run(_agent(model).reply(mk_msg("user", "我喜欢靠窗座位", role="user")))
    from utils.as_compat import msg_json

    data = msg_json(result, default={})
    assert data["intents"][0]["type"] == "preference"
