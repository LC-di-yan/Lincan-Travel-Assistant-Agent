# -*- coding: utf-8 -*-
"""数字逐字校验器 + Answerer 行为。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_core.answerer import Answerer, verify_numbers  # noqa: E402

SRC = "标准：不超过500元/晚\n推荐：协议酒店8-9折\n30个自然日内提交\n建议提前7-14天预订"


def test_verify_numbers_passes_exact_quotes():
    assert verify_numbers("一线城市不超过500元/晚，协议酒店8-9折", SRC) == []
    assert verify_numbers("提前7-14天预订最优惠", SRC) == []


def test_verify_numbers_catches_fabrication():
    assert "1500元" in verify_numbers("一线城市不超过1500元/晚", SRC)
    assert "3天" in verify_numbers("报销要在3天内提交", SRC)


def test_verify_numbers_ignores_list_numbering():
    assert verify_numbers("1. 先看驳回原因 2. 修改后重交", SRC) == []


def test_answerer_flags_unfixable_numbers():
    calls = {"n": 0}

    class BadModel:
        async def __call__(self, messages):
            calls["n"] += 1
            return type("R", (), {"content": json.dumps({
                "answer": "一线城市住宿不超过600元/晚。", "proactive_question": ""})})()

    ans = Answerer(model=BadModel())
    docs = [{"path": "测试｜住宿标准", "text": SRC}]
    import asyncio
    res = asyncio.run(ans.generate("一线城市住宿标准是多少", docs))
    assert calls["n"] == 2, "应有一次修复重试"
    assert res.number_check == "failed"
    assert "未能在与引用条款逐字核对" in res.answer or "未能与引用条款逐字核对" in res.answer


def test_answerer_passes_on_exact_quote():
    class GoodModel:
        async def __call__(self, messages):
            return type("R", (), {"content": json.dumps({
                "answer": "一线城市住宿不超过500元/晚。", "proactive_question": "需要查二线标准吗？"})})()

    ans = Answerer(model=GoodModel())
    docs = [{"path": "测试｜住宿标准", "text": SRC}]
    import asyncio
    res = asyncio.run(ans.generate("一线城市住宿标准是多少", docs))
    assert res.number_check == "passed"
    assert res.proactive_question == "需要查二线标准吗？"