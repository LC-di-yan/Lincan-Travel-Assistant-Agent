"""决策层快速基准（不依赖 pytest，秒级看结果）。

与 tests/test_decision_eval.py 共用同一份用例与题面：
    tests/decision_eval/cases.json  +  utils/decision_schema.py
所以"这里看到的就是线上跑的"。

用法：
    $env:TR_KEY="sk-…"; python tools/bench_decision.py
    python tools/bench_decision.py --key sk-… --verbose

指标：
    is_request  是否请求（陈述/闲聊应为 False）
    gates       必须为真的门控是否都被点亮
    intent      top-1 是否在允许集合内（仅对 request=True 的用例计分）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.decision_engine import DecisionEngine  # noqa: E402

CASES = os.path.join(ROOT, "tests", "decision_eval", "cases.json")


def mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else "***"


async def main() -> int:
    ap = argparse.ArgumentParser(description="决策层快速基准")
    ap.add_argument("--key", default=os.environ.get("TR_KEY") or os.environ.get("NEOHOUSE_API_KEY", ""))
    ap.add_argument("--base", default=os.environ.get("NEOHOUSE_BASE_URL", "https://tokenrhythm.studio/v1"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not args.key:
        print(__doc__)
        print("缺少 key：设置 $env:TR_KEY 或传 --key")
        return 2

    os.environ.setdefault("ALIGO_DECISION_MODE", "assist")
    engine = DecisionEngine(api_key=args.key, base_url=args.base, mode="assist")

    cases = json.loads(open(CASES, encoding="utf-8").read())["cases"]
    hit_req = hit_gate = hit_intent = 0
    intent_total = 0
    lat = []

    print(f"base_url : {args.base}")
    print(f"api_key  : {mask(args.key)}\n")

    for c in cases:
        d = await engine.route(c["q"])
        if d is None:
            print(f"{c['id']}  ERROR  {engine.last_error}")
            continue
        lat.append(d.latency_ms)
        req_ok = d.is_request == c["req"]
        hit_req += int(req_ok)
        if c["req"]:
            gate_ok = set(c["gates"]) <= set(d.active_gates)
            intent_ok = d.intent in c["intent"]
            intent_total += 1
            hit_intent += int(intent_ok)
        else:
            gate_ok, intent_ok = (not d.active_gates), True
        hit_gate += int(gate_ok)

        flag = "PASS" if (req_ok and gate_ok and intent_ok) else "MISS"
        print(f"{c['id']:<8}{flag}  req={str(d.is_request):<5}({d.p_is_request:.2f}) "
              f"intent={d.intent:<18}({d.p_intent:.2f}) gates={d.active_gates} {d.latency_ms:.0f}ms")
        if args.verbose and (not req_ok or not gate_ok or not intent_ok):
            print(f"         期望 req={c['req']} gates={c['gates']} intent∈{c['intent']} | {c['q']}")

    n = len(cases)
    lat.sort()
    print(f"\nis_request {hit_req}/{n} = {hit_req / n:.1%}")
    print(f"gates      {hit_gate}/{n} = {hit_gate / n:.1%}")
    print(f"intent     {hit_intent}/{max(1, intent_total)} = {hit_intent / max(1, intent_total):.1%}")
    if lat:
        print(f"耗时       中位 {lat[len(lat) // 2]:.0f}ms  P90 {lat[min(len(lat) - 1, int(len(lat) * 0.9))]:.0f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
