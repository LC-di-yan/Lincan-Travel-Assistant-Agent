"""决策层金标准集离线评测（需要真实接口，默认跳过）。

跑法：
    $env:NEOHOUSE_API_KEY="sk-…"; $env:ALIGO_DECISION_EVAL="1"
    python -m pytest tests/test_decision_eval.py -q -s

门禁（金标准集 24 条，2026-11-06 基线见 docs/decision-layer-dev-plan.md）：
    is_request ≥ 75% ｜ 门控判定 ≥ 60% ｜ 意图 top-1 ≥ 70%
数值按当前阈值表；调完阈值/题面后重跑，低于门禁说明改动需要回退。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utils.decision_engine import DecisionEngine
from utils.decision_schema import GATES

CASES_PATH = Path(__file__).parent / "decision_eval" / "cases.json"
LIVE = os.environ.get("ALIGO_DECISION_EVAL") == "1" and bool(os.environ.get("NEOHOUSE_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not LIVE, reason="需要 NEOHOUSE_API_KEY 且 ALIGO_DECISION_EVAL=1"),
]


def _load_cases():
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return data["cases"]


async def test_golden_set_accuracy():
    # 评测只关心 key；模式默认 off 时临时打开，不影响部署配置
    if os.environ.get("ALIGO_DECISION_MODE", "off") == "off":
        os.environ["ALIGO_DECISION_MODE"] = "assist"
    engine = DecisionEngine.from_env()
    assert engine is not None, "决策层未配置（NEOHOUSE_API_KEY 缺失）"

    cases = _load_cases()
    hit_req = hit_gate = hit_intent = 0
    intent_total = 0
    wrong = []

    for case in cases:
        decision = await engine.route(case["q"])
        assert decision is not None, f"{case['id']} 决策返回 None: {engine.last_error}"

        req_ok = decision.is_request == case["req"]
        hit_req += int(req_ok)

        if case["req"]:
            want = set(case["gates"])
            got = set(decision.active_gates)
            gate_ok = want <= got
            intent_ok = decision.intent in case["intent"]
            intent_total += 1
            hit_intent += int(intent_ok)
        else:
            gate_ok = not decision.active_gates
            intent_ok = True

        hit_gate += int(gate_ok)
        if not (req_ok and gate_ok and intent_ok):
            wrong.append((case["id"], case["q"], decision.intent, decision.active_gates,
                          decision.p_is_request, decision.p_intent))

    n = len(cases)
    rate_req = hit_req / n
    rate_gate = hit_gate / n
    rate_intent = hit_intent / max(1, intent_total)

    print(f"\nis_request {hit_req}/{n} = {rate_req:.1%}")
    print(f"gates      {hit_gate}/{n} = {rate_gate:.1%}")
    print(f"intent     {hit_intent}/{intent_total} = {rate_intent:.1%}")
    for w in wrong:
        print(f"  MISS {w[0]} {w[1][:28]:<30} intent={w[2]} gates={w[3]} p_req={w[4]} p={w[5]}")

    assert rate_req >= 0.75, f"is_request 准确率 {rate_req:.1%} < 75%"
    assert rate_gate >= 0.60, f"门控准确率 {rate_gate:.1%} < 60%"
    assert rate_intent >= 0.70, f"意图准确率 {rate_intent:.1%} < 70%"
