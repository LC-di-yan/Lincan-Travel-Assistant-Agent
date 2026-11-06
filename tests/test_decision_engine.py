"""决策层单测（不联网）。

覆盖：配置解析、响应归一化、阈值/冲突判定、熔断与 403 降级、影子日志、
veto/rescue 规则、与 IntentionAgent 的接线（shadow 模式不阻塞、不改结果）。
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import decision_engine as de
from utils import decision_router as dr
from utils.decision_schema import intention_from_decision, build_state, build_questions
from utils.decision_thresholds import DEFAULT_THRESHOLDS, load_thresholds
from utils.decision_types import RouteDecision


# ── fixtures ────────────────────────────────────────────────
SAMPLE_PAYLOAD = {
    "model": "NeoHorse-Jev-4B",
    "answers": {
        "is_request": {"type": "noul", "noul": 0.97},
        "intent": {
            "type": "choice",
            "choice": "hotel_search",
            "probabilities": {"hotel_search": 0.91, "itinerary_planning": 0.05, "chitchat": 0.04},
        },
        "need_clarify": {"type": "noul", "noul": 0.2},
        "want_trip": {"type": "noul", "noul": 0.12},
        "want_hotel": {"type": "noul", "noul": 0.93},
        "want_restaurant": {"type": "noul", "noul": 0.02},
        "want_scenic": {"type": "noul", "noul": 0.03},
        "want_info": {"type": "noul", "noul": 0.01},
        "want_memory": {"type": "noul", "noul": 0.01},
    },
    "input_tokens": 390,
    "decision_seconds": 0.055,
}


def make_engine(mode: str = "assist") -> de.DecisionEngine:
    return de.DecisionEngine(api_key="sk-test-1234567890abcd", mode=mode, timeout=1.0)


@pytest.fixture(autouse=True)
def clean_engine():
    dr._pending.clear()
    yield
    de.reset_engine(None)
    dr._pending.clear()


# ── 配置 ────────────────────────────────────────────────────
def test_from_env_off_returns_none(monkeypatch):
    monkeypatch.setenv("ALIGO_DECISION_MODE", "off")
    monkeypatch.setenv("NEOHOUSE_API_KEY", "sk-x")
    assert de.DecisionEngine.from_env() is None


def test_from_env_without_key_returns_none(monkeypatch):
    monkeypatch.setenv("ALIGO_DECISION_MODE", "shadow")
    monkeypatch.delenv("NEOHOUSE_API_KEY", raising=False)
    assert de.DecisionEngine.from_env() is None


def test_from_config_builds_engine():
    eng = de.DecisionEngine.from_config({
        "mode": "assist", "api_key": "sk-dict-1234567890", "model": "NeoHorse-Jev-4B",
        "base_url": "https://example.test/v1", "timeout": 3,
    })
    assert eng is not None and eng.mode == "assist" and eng.timeout == 3.0
    assert de.DecisionEngine.from_config({"mode": "off", "api_key": "sk-x"}) is None
    assert de.DecisionEngine.from_config({"mode": "shadow", "api_key": ""}) is None


def test_from_env_shadow(monkeypatch):
    monkeypatch.setenv("ALIGO_DECISION_MODE", "shadow")
    monkeypatch.setenv("NEOHOUSE_API_KEY", "sk-abcdefghijklmnop")
    eng = de.DecisionEngine.from_env()
    assert eng is not None and eng.mode == "shadow" and eng.enabled


# ── 响应归一化 ──────────────────────────────────────────────
def test_parse_builds_decision():
    eng = make_engine()
    d = eng._parse(SAMPLE_PAYLOAD, latency_ms=480.0)
    assert d.intent == "hotel_search"
    assert d.p_intent == pytest.approx(0.91)
    assert d.is_request is True
    assert d.gate_flags["want_hotel"] is True
    assert d.gate_flags["want_trip"] is False
    assert d.active_gates == ["want_hotel"]
    assert d.conflicts == []          # 意图与门控一致
    assert d.input_tokens == 390


def test_parse_detects_conflict():
    eng = make_engine()
    payload = json.loads(json.dumps(SAMPLE_PAYLOAD))
    payload["answers"]["want_hotel"]["noul"] = 0.10   # 意图说酒店，门控说不是
    d = eng._parse(payload, latency_ms=1.0)
    # 原始冲突要留痕（给影子回放看）
    assert d.conflicts and "want_hotel" in d.conflicts[0]
    # 但高置信主意图会把对应门控回填为真（choice 头更准）
    assert d.gate_flags["want_hotel"] is True


def test_parse_does_not_reconcile_low_confidence_intent():
    eng = make_engine()
    payload = json.loads(json.dumps(SAMPLE_PAYLOAD))
    payload["answers"]["intent"]["probabilities"] = {"hotel_search": 0.40, "chitchat": 0.35}
    payload["answers"]["intent"]["choice"] = "hotel_search"
    payload["answers"]["want_hotel"]["noul"] = 0.10
    d = eng._parse(payload, latency_ms=1.0)
    assert d.p_intent == pytest.approx(0.40)
    assert d.gate_flags["want_hotel"] is False    # 低于 p_intent_floor 不回填


def test_margin_and_second_intent():
    d = RouteDecision(intent="a", p_intent=0.7, intent_probs={"a": 0.7, "b": 0.2})
    assert d.second_intent == ("b", 0.2)
    assert d.margin == pytest.approx(0.5)


# ── 失败与降级 ──────────────────────────────────────────────
async def test_route_returns_none_when_disabled():
    eng = de.DecisionEngine(api_key="", mode="assist")
    assert await eng.route("北京天气") is None


async def test_route_returns_none_on_http_error(monkeypatch):
    eng = make_engine()
    err = urllib.error.HTTPError("http://x", 500, "boom", {}, None)

    def boom(payload, timeout):
        raise err

    monkeypatch.setattr(eng, "_post_blocking", boom)
    assert await eng.route("北京天气") is None
    assert "upstream" in eng.last_error


async def test_403_disables_permanently(monkeypatch):
    eng = make_engine()
    err = urllib.error.HTTPError("http://x", 403, "forbidden", {}, None)

    def boom(payload, timeout):
        raise err

    monkeypatch.setattr(eng, "_post_blocking", boom)
    await eng.route("北京天气")
    assert eng.enabled is False
    # 第二次不应再发请求（直接 None）
    assert await eng.route("上海天气") is None


async def test_route_caches_identical_queries(monkeypatch):
    eng = make_engine()
    calls = {"n": 0}

    def fake_post(payload, timeout):
        calls["n"] += 1
        return SAMPLE_PAYLOAD

    monkeypatch.setattr(eng, "_post_blocking", fake_post)
    a = await eng.route("北京有哪些酒店")
    b = await eng.route("北京有哪些酒店")
    assert calls["n"] == 1
    assert a.intent == b.intent == "hotel_search"
    assert a.trace_id != b.trace_id          # 缓存命中也要新 trace，便于日志区分
    await eng.route("上海有哪些酒店")
    assert calls["n"] == 2


async def test_circuit_open_short_circuits():
    eng = make_engine()
    for _ in range(eng.circuit.failure_threshold):
        eng.circuit.record_failure()
    assert await eng.route("北京天气") is None


# ── 影子日志 ────────────────────────────────────────────────
def test_shadow_log_writes_jsonl(tmp_path):
    eng = de.DecisionEngine(api_key="sk-x", mode="shadow", shadow_dir=str(tmp_path))
    from utils.decision_types import ShadowRecord

    eng.log(ShadowRecord(kind="decision", query="q", trace_id="t1", mode="shadow"))
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").strip()
    assert json.loads(line)["trace_id"] == "t1"


def test_shadow_log_off_mode_is_noop(tmp_path):
    eng = de.DecisionEngine(api_key="sk-x", mode="off", shadow_dir=str(tmp_path))
    from utils.decision_types import ShadowRecord

    eng.log(ShadowRecord(kind="decision", query="q", trace_id="t1", mode="off"))
    assert list(tmp_path.glob("*.jsonl")) == []


# ── veto / rescue 规则 ──────────────────────────────────────
def _fast(agent: str) -> dict:
    return {"agent_schedule": [{"agent_name": agent}], "intents": [{"type": agent}]}


def test_veto_when_not_a_request():
    d = RouteDecision(intent="chitchat", p_intent=0.8, intent_probs={"chitchat": 0.8},
                      is_request=False, p_is_request=0.2)
    assert dr._should_veto(d, _fast("hotel_search"), DEFAULT_THRESHOLDS) is True


def test_no_veto_when_intent_is_confident_even_if_is_request_low():
    # 实测翻译/记账的 is_request 会被低估到 0.1–0.35，不能因此误杀
    d = RouteDecision(intent="translation", p_intent=0.60,
                      intent_probs={"translation": 0.60, "hotel_search": 0.30},
                      is_request=False, p_is_request=0.09)
    assert dr._should_veto(d, _fast("hotel_search"), DEFAULT_THRESHOLDS) is False


def test_veto_when_unsure_and_not_a_request():
    d = RouteDecision(intent="itinerary_planning", p_intent=0.40,
                      intent_probs={"itinerary_planning": 0.40}, is_request=False, p_is_request=0.26)
    assert dr._should_veto(d, _fast("hotel_search"), DEFAULT_THRESHOLDS) is True


def test_veto_only_for_risky_agents():
    d = RouteDecision(intent="chitchat", p_intent=0.9, is_request=False, p_is_request=0.1)
    assert dr._should_veto(d, _fast("currency_conversion"), DEFAULT_THRESHOLDS) is False


def test_veto_when_chitchat_confident():
    d = RouteDecision(intent="chitchat", p_intent=0.9, intent_probs={"chitchat": 0.9},
                      is_request=True, p_is_request=0.6)
    assert dr._should_veto(d, _fast("restaurant_search"), DEFAULT_THRESHOLDS) is True


def test_no_veto_when_regex_and_decision_agree():
    d = RouteDecision(intent="hotel_search", p_intent=0.95,
                      intent_probs={"hotel_search": 0.95}, is_request=True, p_is_request=0.95)
    assert dr._should_veto(d, _fast("hotel_search"), DEFAULT_THRESHOLDS) is False


def test_rescue_requires_rescueable_intent():
    d = RouteDecision(intent="hotel_search", p_intent=0.99, is_request=True)
    assert dr._should_rescue(d, None, DEFAULT_THRESHOLDS) is False


def test_rescue_requires_confidence_and_no_conflict():
    d = RouteDecision(intent="translation", p_intent=0.95, is_request=True)
    assert dr._should_rescue(d, None, DEFAULT_THRESHOLDS) is True
    d.conflicts = ["x"]
    assert dr._should_rescue(d, None, DEFAULT_THRESHOLDS) is False


def test_rescue_ignores_is_request_but_rejects_chitchat():
    # 实测翻译请求的 is_request 只有 0.09，不能因此拒绝直通
    d = RouteDecision(intent="translation", p_intent=0.95, is_request=False, p_is_request=0.09)
    assert dr._should_rescue(d, None, DEFAULT_THRESHOLDS) is True
    chat = RouteDecision(intent="chitchat", p_intent=0.99, is_request=False)
    assert dr._should_rescue(chat, None, DEFAULT_THRESHOLDS) is False


def test_rescue_blocked_when_fast_hit():
    d = RouteDecision(intent="translation", p_intent=0.99, is_request=True)
    assert dr._should_rescue(d, _fast("translation"), DEFAULT_THRESHOLDS) is False


# ── 对外契约 ────────────────────────────────────────────────
def test_intention_from_decision_shape():
    got = intention_from_decision("translation", 0.93, "翻译成俄语")
    assert got is not None
    assert got["agent_schedule"][0]["agent_name"] == "translation"
    assert got["intents"][0]["type"] == "translation"
    assert got["needs_clarification"] is False


def test_intention_from_decision_rejects_non_rescueable():
    assert intention_from_decision("hotel_search", 0.99, "北京酒店") is None
    assert intention_from_decision("chitchat", 0.99, "你好") is None


def test_build_state_and_questions_limits():
    state = build_state("北京天气", ["用户: 明天去上海", "助手: 好的"], {"destination": "上海"})
    assert "北京天气" in state and "上海" in state
    q = build_questions()
    assert 1 <= len(q) <= 16
    assert set(q) >= {"is_request", "intent", "need_clarify", "want_hotel"}


# ── 接线：shadow 不阻塞、不改结果 ────────────────────────────
async def test_shadow_mode_keeps_fast_result(monkeypatch):
    eng = make_engine(mode="shadow")
    eng.route = AsyncMock(return_value=RouteDecision(intent="chitchat", p_intent=0.9))
    eng.log = MagicMock()
    monkeypatch.setattr(dr, "get_engine", lambda: eng)

    fast = _fast("hotel_search")
    hook = await dr.maybe_use_decision("我住在北京朝阳区", [], fast)
    assert hook.fast is fast          # 原结果不变
    assert hook.source == "fast"
    await asyncio.sleep(0)            # 让 shadow 任务跑完
    assert eng.log.called


async def test_assist_mode_vetoes_bad_hit(monkeypatch):
    eng = make_engine(mode="assist")
    eng.route = AsyncMock(return_value=RouteDecision(
        intent="chitchat", p_intent=0.92, intent_probs={"chitchat": 0.92, "hotel_search": 0.03},
        is_request=False, p_is_request=0.2))
    eng.log = MagicMock()
    monkeypatch.setattr(dr, "get_engine", lambda: eng)

    hook = await dr.maybe_use_decision("他住的地方离公司很远", [], _fast("hotel_search"))
    assert hook.fast is None and hook.source == "veto"


async def test_assist_mode_skips_call_when_nothing_to_veto(monkeypatch):
    eng = make_engine(mode="assist")
    eng.route = AsyncMock()
    monkeypatch.setattr(dr, "get_engine", lambda: eng)

    hook = await dr.maybe_use_decision("随便聊聊", [], None)
    assert hook.fast is None
    eng.route.assert_not_called()


async def test_primary_mode_rescues_translation(monkeypatch):
    eng = make_engine(mode="primary")
    eng.route = AsyncMock(return_value=RouteDecision(
        intent="translation", p_intent=0.95, intent_probs={"translation": 0.95},
        is_request=True, p_is_request=0.9))
    eng.log = MagicMock()
    monkeypatch.setattr(dr, "get_engine", lambda: eng)

    hook = await dr.maybe_use_decision("翻译成俄语", [], None)
    assert hook.source == "decision"
    assert hook.fast["agent_schedule"][0]["agent_name"] == "translation"


async def test_no_engine_returns_off_hook(monkeypatch):
    monkeypatch.setattr(dr, "get_engine", lambda: None)
    hook = await dr.maybe_use_decision("北京天气", [], None)
    assert hook.fast is None and hook.engine is None


# ── 阈值覆盖 ────────────────────────────────────────────────
def test_thresholds_override_file(tmp_path, monkeypatch):
    path = tmp_path / "th.json"
    path.write_text(json.dumps({"p_intent": 0.77, "per_gate": {"want_hotel": 0.5}}), encoding="utf-8")
    monkeypatch.setattr(de, "load_thresholds", lambda: load_thresholds(str(path)))
    th = load_thresholds(str(path))
    assert th["p_intent"] == 0.77
    assert th["per_gate"]["want_hotel"] == 0.5
    assert th["per_gate"]["want_trip"] == DEFAULT_THRESHOLDS["per_gate"]["want_trip"]
