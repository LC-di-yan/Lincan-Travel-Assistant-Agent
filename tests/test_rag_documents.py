"""知识库问答回归测试（不联网、不加载模型）。

背景（2026-10-22）：
1. 用户问「上海住宿标准是多少」得到「一线城市 500 元/晚」，但答案没有来源，
   看起来像编的；
2. 追问「请帮我查协议酒店优惠」被当成酒店搜索，返回 600+ 家酒店 ——
   问的是制度，不是具体商家；
3. 用户想知道「目前有哪些知识库」，系统没有这个能力。
"""
import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── RAG agent ──────────────────────────────────────────────
_RAG_PATH = ROOT / ".claude" / "skills" / "ask-question" / "script" / "agent.py"
_spec = importlib.util.spec_from_file_location("rag_agent", _RAG_PATH)
rag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rag)


def test_list_documents_returns_all_kb_files():
    docs = rag.list_documents()
    assert len(docs) == 8, f"知识库应有 8 份文档，实际 {len(docs)}"
    files = [d["file"] for d in docs]
    assert "01_travel_standards.txt" in files
    titles = " ".join(d["title"] for d in docs)
    assert "差旅标准" in titles and "报销" in titles


def test_list_pattern_matches_kb_question():
    assert rag._LIST_DOC_PATTERN.search("目前有哪些知识库")
    assert rag._LIST_DOC_PATTERN.search("知识库包含哪些文档")
    assert not rag._LIST_DOC_PATTERN.search("上海住宿标准是多少")


def test_policy_hint_catches_discount_question():
    assert rag._POLICY_HINT.search("协议酒店有什么优惠")
    assert not rag._POLICY_HINT.search("上海有什么推荐酒店")


def test_collect_sources_dedupes_by_file():
    docs = [
        {"metadata": {"parent_doc": "01_travel_standards.txt", "title": "阿里商旅差旅标准和规定 (Part 1)"}},
        {"metadata": {"parent_doc": "01_travel_standards.txt", "title": "阿里商旅差旅标准和规定 (Part 2)"}},
        {"metadata": {"parent_doc": "02_reimbursement_policy.txt", "title": "差旅费用报销规定 (Part 1)"}},
    ]
    sources = rag._collect_sources(docs)
    assert [s["file"] for s in sources] == ["01_travel_standards.txt", "02_reimbursement_policy.txt"]
    assert sources[0]["title"] == "阿里商旅差旅标准和规定"


# ── 意图路由 ───────────────────────────────────────────────
from agents.intention_agent import _fast_match  # noqa: E402


def _intent(q):
    data = _fast_match(q)
    assert data, f"{q} 应该被规则路由命中"
    return data["intents"][0]["type"]


def test_discount_question_goes_to_knowledge_base():
    assert _intent("请帮我查协议酒店优惠") == "rag_knowledge"


def test_standard_question_goes_to_knowledge_base():
    assert _intent("上海住宿标准是多少") == "rag_knowledge"


def test_hotel_recommendation_still_searches_places():
    assert _intent("上海有什么推荐酒店") == "hotel_search"
