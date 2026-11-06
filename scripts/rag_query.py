# -*- coding: utf-8 -*-
"""RAG 检索调试 CLI：看一条问题最终会拿到哪几段原文（不需要 API Key）。

用法：
  python scripts/rag_query.py "杭州住宿费上限是多少"
  python scripts/rag_query.py "日本签证能停留多久" --skill visa
  python scripts/rag_query.py "报销需要哪些材料" --top-k 5 --full

输出 = 与线上完全一致的检索路径（导航 ∪ BM25 → 重排 → 祖先去冗余），
只是不带 LLM 生成，用来排查「为什么答错 / 为什么没命中」。
"""
import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AGENTS = {
    "ask": ROOT / ".claude" / "skills" / "ask-question" / "script" / "agent.py",
    "visa": ROOT / ".claude" / "skills" / "visa-info" / "script" / "agent.py",
}


def load_agent_class(skill: str):
    path = AGENTS[skill]
    spec = importlib.util.spec_from_file_location(f"{skill}_rag_agent", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and name.endswith("Agent") and hasattr(obj, "retrieve"):
            return obj
    raise SystemExit(f"未在 {path} 找到带 retrieve() 的 Agent 类")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 检索调试（无 LLM）")
    parser.add_argument("query", help="用户问题")
    parser.add_argument("--skill", choices=list(AGENTS), default="ask", help="ask=差旅 visa=签证")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--full", action="store_true", help="打印节点全文")
    args = parser.parse_args()

    agent_cls = load_agent_class(args.skill)
    agent = agent_cls(name="debug", model=None)
    docs = asyncio.run(agent.retrieve(args.query, top_k=args.top_k))

    meta = getattr(agent, "_last_retrieval", {})
    print(f"问题：{args.query}")
    print(f"检索：nav_hits={meta.get('nav_hits', 0)} bm25补齐={max(meta.get('bm25_hits', 0), 0)} "
          f"去冗余={meta.get('ancestor_pruned', 0)} degraded={meta.get('degraded')}")
    print(f"返回 {len(docs)} 段：\n")
    for i, d in enumerate(docs, 1):
        text = d["text"] if args.full else d["text"].replace("\n", " ")
        snippet = text[:160] + ("…" if len(text) > 160 else "")
        print(f"[{i}] score={d.get('score', 0):.3f}  {d['path']}")
        print(f"    {d['file']} 行 {d.get('lines')}")
        print(f"    {snippet}\n")
    if not docs:
        print("（空结果：检查 tree_index 是否存在，或问题与知识库无关）")
    return 0 if docs else 1


if __name__ == "__main__":
    sys.exit(main())
