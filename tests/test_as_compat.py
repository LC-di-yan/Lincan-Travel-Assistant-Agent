# -*- coding: utf-8 -*-
"""as_compat 双版本适配层单测（升级计划 §4.P1 验收项）。

在 1.0.16 与 2.0.11 下都必须全绿：这条测试是 P2/P3 大规模改造的行为基准。
"""
from __future__ import annotations

import json

from utils.as_compat import (
    AS_MAJOR,
    as_messages,
    build_chat_model,
    chat_text,
    mk_msg,
    msg_json,
    msg_text,
)


def test_mk_msg_from_dict_roundtrip():
    payload = {"status": "success", "answer": "杭州住宿上限 600 元"}
    m = mk_msg("rag-agent", payload)
    assert msg_json(m) == payload
    # 兼容 1.x（content 为 JSON 字符串）与 2.x（content 为块列表）
    if AS_MAJOR >= 2:
        assert isinstance(m.content, list)
    else:
        assert isinstance(m.content, str)


def test_mk_msg_from_str_keeps_text():
    m = mk_msg("user", "帮我规划杭州三天", role="user")
    assert msg_text(m) == "帮我规划杭州三天"
    assert m.role == "user"


def test_mk_msg_accepts_blocks_passthrough():
    m = mk_msg("assistant", [{"type": "text", "text": "块形式"}])
    assert msg_text(m) == "块形式"


def test_msg_text_falls_back_on_thinking_only():
    m = mk_msg("assistant", [{"type": "thinking", "thinking": "只思考无文本"}])
    assert msg_text(m) == ""
    assert msg_text(m, fallback="兜底") == "兜底"


def test_msg_json_returns_default_on_bad_json():
    m = mk_msg("assistant", "这不是 JSON")
    assert msg_json(m, {"k": 1}) == {"k": 1}


def test_as_messages_version_aware():
    out = as_messages([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
    assert len(out) == 2
    if AS_MAJOR >= 2:
        assert all(not isinstance(x, dict) for x in out)   # 2.x 要 Msg 列表
        assert out[0].role == "system"
    else:
        assert all(isinstance(x, dict) for x in out)       # 1.x 要 dict 列表


def test_chat_text_handles_text_and_content():
    class R:
        def __init__(self, t):
            self.text = t

    assert chat_text(R("你好")) == "你好"
    assert chat_text({"content": "dict 内容"}) == "dict 内容"
    assert chat_text(None, fallback="f") == "f"


def test_build_chat_model_constructs():
    model = build_chat_model({"api_key": "sk-test", "model_name": "glm-5.2-fast-preview",
                              "base_url": "https://example.invalid/v1", "generate_kwargs": {"max_tokens": 128}})
    assert model is not None

def test_chat_text_survives_keyerror_getattr():
    """回归：1.x ChatResponse.__getattr__ 抛 KeyError，getattr(x, name, default) 兜不住。"""

    class LegacyChatResponse:
        """模拟 agentscope 1.0.16 ChatResponse。"""

        def __init__(self, content):
            self._content = content

        def __getattr__(self, name):
            if name == "content":
                return self._content
            raise KeyError(name)

    assert chat_text(LegacyChatResponse("收到")) == "收到"
    assert chat_text(LegacyChatResponse([{"type": "text", "text": "块文本"}])) == "块文本"
    assert chat_text(LegacyChatResponse(""), fallback="fb") == "fb"


def test_extract_llm_text_survives_keyerror_getattr():
    from utils.llm_response import extract_llm_text

    class LegacyChatResponse:
        def __init__(self, content):
            self._content = content

        def __getattr__(self, name):
            if name == "content":
                return self._content
            raise KeyError(name)

    assert extract_llm_text(LegacyChatResponse("你好")) == "你好"
    assert extract_llm_text(LegacyChatResponse(""), fallback="兜底") == "兜底"
