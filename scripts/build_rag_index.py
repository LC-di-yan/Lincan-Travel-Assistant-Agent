# -*- coding: utf-8 -*-
"""重建 RAG 树索引（两个知识库的统一入口）。

用法：
  python scripts/build_rag_index.py            # 全部重建（ask + visa）
  python scripts/build_rag_index.py --ask      # 只重建差旅知识库
  python scripts/build_rag_index.py --visa     # 只重建签证知识库
  python scripts/build_rag_index.py --llm      # 用 LLM 润色节点摘要（需 ALIGO_API_KEY）

说明：
- 树索引产物在 .claude/skills/<skill>/data/tree_index/*.json，可直接 git diff 评审；
- 加载时若源 txt 的 sha256 与索引不一致会标记 stale 并拒绝使用，所以源文档变更后必须重建；
- 结构层级取自文档自带标题（一、/ 1. / Q1:），LLM 只润色摘要，无 Key 也能建（启发式摘要）。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_core.tree_builder import build_all  # noqa: E402

SKILLS = {
    "ask": ROOT / ".claude" / "skills" / "ask-question",
    "visa": ROOT / ".claude" / "skills" / "visa-info",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 RAG 树索引")
    parser.add_argument("--ask", action="store_true", help="重建差旅知识库")
    parser.add_argument("--visa", action="store_true", help="重建签证知识库")
    parser.add_argument("--llm", action="store_true", help="用 LLM 润色摘要（需要 API Key）")
    args = parser.parse_args()

    targets = []
    if args.ask:
        targets.append("ask")
    if args.visa:
        targets.append("visa")
    if not targets:
        targets = list(SKILLS)

    total = 0
    for name in targets:
        skill_dir = SKILLS[name]
        print(f"[{name}] 重建 {skill_dir.name}")
        res = build_all(skill_dir / "data" / "documents", skill_dir / "data" / "tree_index",
                        use_llm=args.llm)
        total += res["built"]
    print(f"\n完成：共 {total} 篇文档重建完成。")
    print("自检：python tests/eval_rag_tree.py")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
