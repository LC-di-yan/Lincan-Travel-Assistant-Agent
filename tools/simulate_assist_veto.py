# -*- coding: utf-8 -*-
"""离线模拟 assist 否决行为：用真实影子样本评估「切 assist 是收益还是风险」。

口径：assist 只在正则命中 RISKY_AGENTS 时才可能否决（_should_veto）。
对每条 fast 样本重放否决判定，并人工可读地列出「否决后交给 LLM」的影响。
"""
import glob, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.decision_router import _should_veto
from utils.decision_schema import RISKY_AGENTS
from utils.decision_thresholds import load_thresholds
from utils.decision_types import RouteDecision

FIELDS = {f for f in RouteDecision.__dataclass_fields__}
th = load_thresholds()

rows = []
for f in sorted(glob.glob("data/decision_shadow/*.jsonl")):
    for line in Path(f).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try: rows.append(json.loads(line))
            except Exception: pass

dec = {r["trace_id"]: r for r in rows if r.get("kind") == "decision" and r.get("trace_id")}
out = {r["trace_id"]: r for r in rows if r.get("kind") == "outcome" and r.get("trace_id")}

print("RISKY_AGENTS =", sorted(RISKY_AGENTS))
print(f"paired={len([t for t in dec if t in out])}  decisions={len(dec)}")
print()

fast_n = veto_n = 0
vetoes = []
for tid, d in dec.items():
    o = out.get(tid)
    if not o or o.get("final_path") != "fast":
        continue
    fast_n += 1
    payload = {k: v for k, v in (d.get("decision") or {}).items() if k in FIELDS}
    try:
        rd = RouteDecision(**payload)
    except Exception as e:
        print("skip", tid, e); continue
    fast = {"agent_schedule": [{"agent_name": a} for a in (d.get("regex_agents") or [])],
            "intents": [{"type": t} for t in (d.get("regex_intents") or [])]}
    if _should_veto(rd, fast, th):
        veto_n += 1
        vetoes.append((d.get("query",""), rd.intent, rd.p_intent, d.get("regex_intents") or []))

print(f"fast 路径样本 = {fast_n}")
print(f"assist 会否决 = {veto_n}  ({veto_n/max(fast_n,1)*100:.1f}% of fast)")
print()
for q, intent, p, regex in vetoes:
    print(f"  VETO  {q[:30]:32s} 决策={intent}({p:.2f})  正则={regex}")