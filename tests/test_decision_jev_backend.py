# -*- coding: utf-8 -*-
"""决策层 TypeSafe/Jev 后端单测（P7 决策项）。

不触网：JevDecisionBackend 的网络层被替换为假实现，验证
题面翻译 → ClassifierResponse → 线格式 → RouteDecision 的完整链路。
真实端到端（/v1/systemone + sk_tr_ key）需线上 key，见 docs/as2-ab-report.md。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from utils import decision_jev
from utils.decision_jev import JevDecisionBackend, to_wire, translate_questions
from utils.decision_schema import build_questions


# ── 题面翻译 ────────────────────────────────────────────────
def test_translate_questions_maps_all_types():
    qs = build_questions()
    types = {name: q["type"] for name, q in qs.items()}
    assert "noul" in set(types.values()) and "choice" in set(types.values())

    translated = translate_questions(qs)
    assert set(translated) == set(qs)
    for name, q in translated.items():
        t = type(q).__name__
        if qs[name]["type"] == "noul":
            assert t == "BinaryQuestion"
        elif qs[name]["type"] == "choice":
            assert t == "ChoiceQuestion"
            # choice 的 criteria（INTENT_CRITERIA dict[str,str]）原样透传
            assert q.criteria == qs[name]["criteria"]


def test_translate_unknown_type_raises():
    with pytest.raises(ValueError, match="未知题面类型"):
        translate_questions({"bad": {"type": "unknown_kind", "instructions": "x"}})


# ── 线格式归一化 ────────────────────────────────────────────
def _make_response(answers: dict, include_usage=True):
    from agentscope.classifier import ClassifierResponse
    from agentscope.classifier._response import (
        BinaryAnswer,
        ChoiceAnswer,
        RefusalAnswer,
    )
    from agentscope.classifier._usage import ClassifierUsage

    content = {}
    for name, spec in answers.items():
        if spec["kind"] == "binary":
            content[name] = BinaryAnswer(probability=spec["probability"])
        elif spec["kind"] == "choice":
            content[name] = ChoiceAnswer(
                choice=spec["choice"], confidence=spec.get("confidence", 0.9),
                probabilities=spec.get("probabilities", {}),
            )
        elif spec["kind"] == "refusal":
            content[name] = RefusalAnswer()
    usage = ClassifierUsage(time=0.1, input_tokens=123) if include_usage else None
    return ClassifierResponse(model="NeoHorse-Jev-4B", content=content, usage=usage)


def test_to_wire_maps_binary_and_choice():
    resp = _make_response({
        "is_request": {"kind": "binary", "probability": 0.91},
        "intent": {"kind": "choice", "choice": "hotel_search",
                   "probabilities": {"hotel_search": 0.88, "chitchat": 0.02}},
    })
    wire = to_wire(resp)
    assert wire["answers"]["is_request"] == {"noul": 0.91}
    assert wire["answers"]["intent"]["choice"] == "hotel_search"
    assert wire["answers"]["intent"]["probabilities"]["chitchat"] == 0.02
    assert wire["input_tokens"] == 123


def test_to_wire_refusal_raises():
    resp = _make_response({"is_request": {"kind": "refusal"}})
    with pytest.raises(ValueError, match="拒答"):
        to_wire(resp)


# ── DecisionEngine 集成（backend="jev"）────────────────────
class _FakeJevBackend:
    """替身：返回固定线格式，验证 decide → _parse 链路。"""

    def __init__(self, api_key, base_url, model, timeout):
        self.init_args = (api_key, base_url, model, timeout)

    async def decide(self, state, questions, timeout=None):
        answers = {}
        for name, q in questions.items():
            if q["type"] == "choice":
                answers[name] = {"choice": "hotel_search", "confidence": 0.91,
                                 "probabilities": {"hotel_search": 0.91}}
            else:
                answers[name] = {"noul": 0.93}
        return {"model": "NeoHorse-Jev-4B", "answers": answers,
                "input_tokens": 200, "decision_seconds": 0.35}


def test_engine_jev_backend_end_to_end(monkeypatch):
    from utils.decision_engine import DecisionEngine

    monkeypatch.setattr(decision_jev, "JevDecisionBackend", _FakeJevBackend)
    engine = DecisionEngine(api_key="sk_tr_test", mode="assist", backend="jev")
    decision = asyncio.run(engine.route("杭州出差一周住哪", history=[], entities={}))

    assert decision is not None
    assert decision.intent == "hotel_search"
    assert decision.is_request is True
    assert decision.p_intent == pytest.approx(0.91, abs=1e-3)
    # jev 后端收到的凭据与引擎一致
    assert engine._jev_backend.init_args[0] == "sk_tr_test"


def test_engine_default_backend_is_custom():
    from utils.decision_engine import DecisionEngine

    engine = DecisionEngine(api_key="k", mode="assist")
    assert engine.backend == "custom" and engine._jev_backend is None


def test_from_config_passes_backend():
    from utils.decision_engine import DecisionEngine

    engine = DecisionEngine.from_config({"mode": "assist", "api_key": "k", "backend": "jev"})
    assert engine is not None and engine.backend == "jev"
