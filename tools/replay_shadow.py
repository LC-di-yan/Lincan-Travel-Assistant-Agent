"""影子日志回放：算"决策层 vs 现有链路"的一致率与修正率。

输入：data/decision_shadow/YYYYMMDD.jsonl（由 utils/decision_router.py 写入）
输出：终端报表 + 可选 CSV

用法：
    python tools/replay_shadow.py
    python tools/replay_shadow.py --dir data/decision_shadow --date 20261106
    python tools/replay_shadow.py --csv shadow_report.csv

指标口径：
    - decision.kind="decision" 记录模型当时的判断；
    - decision.kind="outcome" 记录本次请求最终走了哪条路（fast/decision/llm/veto）；
    - 一致 = 模型的 top1 意图 ∈ 最终调度的意图集合（或 chitchat 对应 final_path=llm 且无 agent）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_records(directory: str, date: str = "") -> List[Dict[str, Any]]:
    if not os.path.isdir(directory):
        return []
    files = sorted(
        f for f in os.listdir(directory)
        if f.endswith(".jsonl") and (not date or f.startswith(date))
    )
    rows: List[Dict[str, Any]] = []
    for name in files:
        path = os.path.join(directory, name)
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def join(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    decisions: Dict[str, Dict[str, Any]] = {}
    outcomes: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        tid = r.get("trace_id") or ""
        if not tid:
            continue
        if r.get("kind") == "decision":
            decisions[tid] = r
        elif r.get("kind") == "outcome":
            outcomes[tid] = r

    pairs = []
    for tid, dec in decisions.items():
        pairs.append({"trace_id": tid, "decision": dec, "outcome": outcomes.get(tid)})
    return pairs


def report(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(pairs)
    joined = [p for p in pairs if p["outcome"]]
    stats: Dict[str, Any] = {
        "total": total,
        "joined": len(joined),
        "paths": Counter(p["outcome"].get("final_path", "?") for p in joined),
        "intents": Counter((p["decision"].get("decision") or {}).get("intent", "?") for p in pairs),
        "agree": 0,
        "disagree_examples": [],
        "latency": [],
        "conflicts": 0,
        "errors": 0,
    }

    for p in pairs:
        dec = p["decision"].get("decision") or {}
        if dec.get("conflicts"):
            stats["conflicts"] += 1
        if dec.get("latency_ms"):
            stats["latency"].append(float(dec["latency_ms"]))

    for p in joined:
        dec = p["decision"].get("decision") or {}
        out = p["outcome"] or {}
        pred = dec.get("intent")
        finals = set(out.get("final_intents") or [])
        path = out.get("final_path", "")
        if pred == "chitchat":
            agree = path == "llm" and not out.get("final_agents")
        else:
            agree = pred in finals
        if agree:
            stats["agree"] += 1
        elif len(stats["disagree_examples"]) < 20:
            stats["disagree_examples"].append({
                "query": p["decision"].get("query", "")[:40],
                "pred": pred,
                "p": dec.get("p_intent"),
                "final_path": path,
                "final_agents": out.get("final_agents"),
            })
    return stats


def print_report(stats: Dict[str, Any]) -> None:
    print(f"记录数        : {stats['total']}（其中 {stats['joined']} 条有结局）")
    if stats["joined"]:
        rate = stats["agree"] / stats["joined"] * 100
        print(f"意图一致率    : {stats['agree']}/{stats['joined']} = {rate:.1f}%")
    print(f"冲突条数      : {stats['conflicts']}")
    if stats["latency"]:
        lat = sorted(stats["latency"])
        n = len(lat)
        print(f"决策耗时      : 中位 {lat[n // 2]:.0f}ms  P90 {lat[min(n - 1, int(n * 0.9))]:.0f}ms")
    print(f"最终路径分布  : {dict(stats['paths'])}")
    print(f"模型意图分布  : {dict(stats['intents'])}")
    if stats["disagree_examples"]:
        print("\n不一致样例（最多 20 条）：")
        for ex in stats["disagree_examples"]:
            print(f"  {ex['query']:<30} pred={ex['pred']}({ex['p']})  final={ex['final_path']} {ex['final_agents']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="回放决策层影子日志")
    ap.add_argument("--dir", default=os.path.join(ROOT, "data", "decision_shadow"))
    ap.add_argument("--date", default="", help="YYYYMMDD，留空=全部")
    ap.add_argument("--csv", default="", help="导出明细 CSV 路径")
    args = ap.parse_args()

    rows = load_records(args.dir, args.date)
    if not rows:
        print(f"没有找到影子日志：{args.dir}（先设 ALIGO_DECISION_MODE=shadow 跑一会儿）")
        return 1

    pairs = join(rows)
    stats = report(pairs)
    print_report(stats)

    if args.csv:
        import csv
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["trace_id", "query", "pred_intent", "p_intent", "final_path", "final_agents"])
            for p in pairs:
                dec = p["decision"].get("decision") or {}
                out = p["outcome"] or {}
                writer.writerow([p["trace_id"], p["decision"].get("query", ""), dec.get("intent"),
                                 dec.get("p_intent"), out.get("final_path"), "|".join(out.get("final_agents") or [])])
        print(f"\n明细已导出：{args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
