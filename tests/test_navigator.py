# -*- coding: utf-8 -*-
"""树导航器（规则直通 / LLM 下钻 / 降级）。"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_core.tree_store import TreeStore   # noqa: E402
from rag_core.navigator import Navigator    # noqa: E402


def _store():
    st = TreeStore()
    assert st.load(), st.errors
    return st


def test_route_by_rules_hits_travel_standards():
    nav = Navigator(_store(), model=None)
    assert "01_travel_standards" in nav.route_by_rules("北京出差的住宿标准是多少？")


def test_rule_path_no_model_finds_accommodation():
    nav = Navigator(_store(), model=None)
    res = asyncio.run(nav.navigate("一线城市出差住宿标准是多少"))
    assert res.hits, "无模型也应走规则直通"
    texts = [nav.store.node_text(h.doc_id, h.node_id) for h in res.hits]
    assert any("不超过500元/晚" in t for t in texts), texts


def test_no_model_unknown_query_degrades():
    nav = Navigator(_store(), model=None)
    res = asyncio.run(nav.navigate("今天外面天气怎么样"))
    assert not res.hits or res.degraded


def _llm_stub(response: dict):
    class R:
        content = json.dumps(response, ensure_ascii=False)
    class M:
        async def __call__(self, messages):
            return R()
    return M()


def test_llm_low_confidence_degrades():
    nav = Navigator(_store(), model=_llm_stub({"doc_ids": ["01_travel_standards"], "confidence": 0.2}))
    res = asyncio.run(nav.navigate("完全无关的问题xyz"))
    assert res.degraded


def test_llm_descend_selects_node():
    """桩 LLM：第一层选「住宿标准」并展开，第二层选「一线城市」叶子。"""
    class M2:
        async def __call__(self, messages):
            text = messages[-1]["content"]
            # 叶子层（候选里已出现叶子 id）→ 直接选叶子；否则选 H1 并要求展开
            if "01#h1-3#h2-1" in text:
                return type("R", (), {"content": json.dumps({"selected": ["01#h1-3#h2-1"], "expand": False, "confidence": 0.9})})()
            if "01#h1-3" in text:
                return type("R", (), {"content": json.dumps({"selected": ["01#h1-3"], "expand": True, "confidence": 0.9})})()
            return type("R", (), {"content": json.dumps({"selected": ["01#h1-2"], "expand": False, "confidence": 0.9})})()

    import rag_core.navigator as nav_mod
    orig = nav_mod._title_matches
    nav_mod._title_matches = lambda q, t: False   # 关掉规则直通，强制走 LLM 分支
    try:
        nav = Navigator(_store(), model=M2())
        # 验证「LLM 选 H1 展开 → 选叶子」两跳路径
        hits, calls, degraded = asyncio.run(nav.descend("alpha beta 检索演练", "01_travel_standards"))
    finally:
        nav_mod._title_matches = orig
    assert any(h.node_id == "01#h1-3#h2-1" for h in hits), [(h.doc_id, h.node_id) for h in hits]
    assert calls >= 1 and not degraded