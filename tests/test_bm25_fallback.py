# -*- coding: utf-8 -*-
"""BM25 词面兜底。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_core.tree_store import TreeStore     # noqa: E402
from rag_core.bm25_fallback import BM25Fallback  # noqa: E402


def _bm():
    st = TreeStore()
    st.load()
    return BM25Fallback(st)


def test_exact_policy_terms_rank():
    bm = _bm()
    # 纯词面能稳定命中的：唯一数字串 / 专有词
    top = [r["text"] for r in bm.search("增值税发票", top_k=5)]
    assert any("增值税发票" in t for t in top), top[:2]
    top2 = [r["text"] for r in bm.search("400-800-8888", top_k=5)]
    assert any("400-800-8888" in t for t in top2)


def test_empty_and_noise_queries():
    bm = _bm()
    assert bm.search("", top_k=3) == []


def test_all_nodes_indexed():
    st = TreeStore(); st.load()
    bm = _bm()
    total = sum(len(d.nodes()) for d in st.docs.values())
    assert len(bm._ids) >= total - 10  # 个别节点可能无文本