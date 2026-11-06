# -*- coding: utf-8 -*-
"""树索引构建与加载（M0 验收）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_core.tree_builder import build_all, parse_document   # noqa: E402
from rag_core.tree_store import TreeStore                     # noqa: E402

DOC_DIR = ROOT / ".claude" / "skills" / "ask-question" / "data" / "documents"


def test_parse_document_structure():
    doc = parse_document(DOC_DIR / "01_travel_standards.txt")
    titles = [n["title"] for n in doc["h1"]]
    assert any("住宿标准" in t for t in titles), titles
    h1 = next(n for n in doc["h1"] if "住宿标准" in n["title"])
    child_titles = " ".join(c["title"] for c in h1["children"])
    assert "一线城市住宿标准" in child_titles
    # 行号连续且不越界
    total = len(doc["lines"])
    for n in doc["h1"]:
        assert 1 <= n["line_range"][0] <= n["line_range"][1] <= total + 1


def test_build_all_and_store_roundtrip(tmp_path):
    index_dir = tmp_path / "tree_index"
    res = build_all(DOC_DIR, index_dir)
    assert res["built"] == 8
    assert (index_dir / "manifest.json").exists()
    doc = json.loads((index_dir / "01_travel_standards.json").read_text(encoding="utf-8"))
    assert doc["doc_id"] == "01_travel_standards"
    assert doc["keywords"], "关键词抽取不应为空"

    store = TreeStore(index_dir=index_dir, documents_dir=DOC_DIR)
    assert store.load(), store.errors
    assert len(store.docs) == 8
    # 节点原文切片：一线城市住宿标准应包含 500元/晚
    node_id = "01#h1-3#h2-1"
    text = store.node_text("01_travel_standards", node_id)
    assert "不超过500元/晚" in text
    assert "一线城市" in store.path_of("01_travel_standards", node_id)


def test_store_detects_stale_source(tmp_path):
    docs_copy = tmp_path / "documents"
    docs_copy.mkdir()
    for p in DOC_DIR.glob("*.txt"):
        (docs_copy / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    index_dir = tmp_path / "tree_index"
    build_all(docs_copy, index_dir)

    store = TreeStore(index_dir=index_dir, documents_dir=docs_copy)
    assert store.load()

    # 源文档被修改 → 树过期
    target = docs_copy / "01_travel_standards.txt"
    target.write_text(target.read_text(encoding="utf-8") + "\n临时追加行\n", encoding="utf-8")
    store2 = TreeStore(index_dir=index_dir, documents_dir=docs_copy)
    store2.load(auto_build=False)
    assert store2.docs["01_travel_standards"].stale