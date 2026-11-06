# -*- coding: utf-8 -*-
"""离线建树：documents/*.txt → tree_index/*.json + manifest.json

结构层级直接取自文档自带的标题（一、/ 1. / Q1:），LLM 只用于把摘要写得更「可导航」，
没有 API Key 时用启发式摘要（数值事实 + 首行），保证离线可建、结果可 diff。

用法：
  python .claude/skills/ask-question/script/tree_builder.py            # 全量重建
  python .claude/skills/ask-question/script/tree_builder.py --doc 01_travel_standards
  python .claude/skills/ask-question/script/tree_builder.py --no-llm   # 强制启发式摘要
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

H1_RE = re.compile(r"^\s*([一二三四五六七八九十]{1,3})、\s*(\S.*)$")
H2_RE = re.compile(r"^\s*(\d{1,2})[\.、]\s*(\S.{0,44})$")
QA_RE = re.compile(r"^\s*(Q\d{1,3})\s*[:：]\s*(\S.*)$")
BULLET_RE = re.compile(r"^\s*(?:[-•·]|\(?[a-h]\)|\d+\))")
FACT_RE = re.compile(r"\d[\d,，\.]{0,6}\s*(?:元|万元|小时|天|个工作日|公里|%|％|折|分钟|个月|个月|个月|人|座|米|条|类|档|公里)")

MAX_SUMMARY = 60


def _clean_line(s: str) -> str:
    return s.strip()


def _clip(s: str, n: int = MAX_SUMMARY) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -·、；;，")
    return s if len(s) <= n else s[:n - 1] + "…"


def _facts(body: List[str]) -> List[str]:
    """抽正文里的「数字+单位」事实，作为启发式摘要。"""
    seen: List[str] = []
    for line in body:
        for m in FACT_RE.finditer(line):
            t = m.group(0).replace("，", ",").strip()
            if t not in seen:
                seen.append(t)
            if len(seen) >= 5:
                return seen
    return seen


def parse_document(path: Path) -> dict:
    """把一篇 txt 解析成两级树（H1 → H2/Q）。正文归属最内层标题。"""
    lines = path.read_text(encoding="utf-8").split("\n")
    doc_num = path.stem.split("_", 1)[0]
    doc_id = path.stem
    title = next((_clean_line(l) for l in lines if l.strip()), path.stem)

    h1_nodes: List[dict] = []
    cur_h1: Optional[dict] = None
    cur_h2: Optional[dict] = None

    def close_h2(end_line: int):
        nonlocal cur_h2
        if cur_h1 is not None and cur_h2 is not None:
            cur_h2["line_range"][1] = end_line
            cur_h1["children"].append(cur_h2)
            cur_h2 = None

    def close_h1(end_line: int):
        nonlocal cur_h1
        if cur_h1 is not None:
            cur_h1["line_range"][1] = end_line
            h1_nodes.append(cur_h1)
            cur_h1 = None

    for idx, raw_line in enumerate(lines, start=1):
        s = _clean_line(raw_line)
        if not s:
            continue
        if idx == 1:
            continue  # 文档标题行
        if BULLET_RE.match(raw_line):
            continue

        m1 = H1_RE.match(s)
        if m1 and len(s) <= 44:
            close_h2(idx - 1)
            close_h1(idx - 1)
            cur_h1 = {
                "id": f"{doc_num}#h1-{len(h1_nodes) + 1}",
                "title": _clip(s, 44),
                "summary": "",
                "line_range": [idx, idx],
                "children": [],
            }
            continue

        is_heading_like = len(s) <= 46 and not s.endswith(("。", "；", ";", "，", ","))
        m2 = H2_RE.match(s) if is_heading_like else None
        mq = QA_RE.match(s) if is_heading_like else None
        if (m2 or mq) and cur_h1 is not None:
            close_h2(idx - 1)
            t = (mq.group(1) + " " + _clip(mq.group(2), 40)) if mq else _clip(s, 44)
            cur_h2 = {
                "id": f"{cur_h1['id']}#h2-{len(cur_h1['children']) + 1}",
                "title": t,
                "summary": "",
                "line_range": [idx, idx],
                "children": [],
            }
            continue

        # 普通内容行 → 归属当前最内层节点
        if cur_h2 is not None:
            cur_h2["line_range"][1] = idx
        elif cur_h1 is not None:
            cur_h1["line_range"][1] = idx

    close_h2(len(lines))
    close_h1(len(lines))
    return {"doc_id": doc_id, "title": title, "h1": h1_nodes, "lines": lines, "path": str(path)}


def _h1_summary(node: dict) -> str:
    if node["children"]:
        titles = []
        for c in node["children"]:
            t = re.sub(r"^(Q\d+\s*[:：]|\d+[\.、]\s*)", "", c["title"]).strip()
            titles.append(_clip(t, 18))
        return _clip("、".join(dict.fromkeys(titles)))
    body = _slice_lines(node["path_lines"], node["line_range"])
    facts = _facts(body)
    if facts:
        return _clip("；".join(facts))
    content = [l.strip(" -•·\t") for l in body[1:] if l.strip()]
    return _clip(content[0] if content else node["title"], 50)


def _leaf_summary(node: dict) -> str:
    """叶子节点摘要：优先「数字+单位」事实，其次首条正文（不重复标题）。"""
    body = _slice_lines(node["path_lines"], node["line_range"])
    facts = _facts(body)
    if facts:
        return _clip("；".join(facts))
    content = [l.strip(" -•·\t") for l in body[1:]
                 if l.strip() and not re.match(r"^A\d+\s*[:：]$", l.strip())]
    first = next((l for l in content if not l.endswith("：")), content[0] if content else "")
    return _clip(first or node["title"], 50)


def _slice_lines(lines: List[str], rng: List[int]) -> List[str]:
    start = max(1, int(rng[0]))
    end = min(len(lines), int(rng[1]))
    return [l for l in lines[start - 1:end] if l.strip()]


def doc_keywords(text: str, topk: int = 14) -> List[str]:
    try:
        import jieba.analyse
        kws = jieba.analyse.extract_tags(text, topK=topk * 2, withWeight=False)
        return [k for k in kws if len(k) >= 2][:topk]
    except Exception as exc:  # noqa: BLE001
        logger.warning("关键词抽取失败（不影响建树）：%s", exc)
        return []


def build_doc(path: Path, use_llm: bool = False) -> dict:
    parsed = parse_document(path)
    lines = parsed["lines"]
    tree = []
    for h1 in parsed["h1"]:
        node = {
            "id": h1["id"],
            "title": h1["title"],
            "summary": "",
            "line_range": list(h1["line_range"]),
            "children": [],
        }
        ctx = {"path_lines": lines}
        for h2 in h1["children"]:
            h2["path_lines"] = lines
            node["children"].append({
                "id": h2["id"],
                "title": h2["title"],
                "summary": _leaf_summary(h2),
                "line_range": list(h2["line_range"]),
                "children": [],
            })
        h1["path_lines"] = lines
        if node["children"]:
            node["summary"] = _h1_summary_from_children(node)
        else:
            node["summary"] = _leaf_summary(h1)
        tree.append(node)

    full_text = "\n".join(lines)
    h1_titles = "、".join(re.sub(r"^[一二三四五六七八九十]+、", "", n["title"]) for n in tree)
    doc = {
        "schema_version": 1,
        "doc_id": parsed["doc_id"],
        "source_file": parsed["path"],
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "title": parsed["title"],
        "summary": _clip(h1_titles, 80),
        "keywords": doc_keywords(full_text),
        "tree": tree,
    }
    if use_llm:
        _llm_polish(doc)
    return doc


def _h1_summary_from_children(node: dict) -> str:
    titles = []
    for c in node["children"]:
        t = re.sub(r"^(Q\d+\s*[:：]|\d+[\.、]\s*)", "", c["title"]).strip()
        titles.append(_clip(t, 18))
    return _clip("、".join(dict.fromkeys(titles)))


def _llm_polish(doc: dict) -> None:
    """可选：用 LLM 把 doc/节点摘要改写成更利于导航的一句话。失败则保留启发式摘要。"""
    try:
        from config import LLM_CONFIG
        if not LLM_CONFIG.get("api_key"):
            return
        import asyncio
        from utils.llm_response import extract_llm_text, extract_json_object

        async def run():
            from utils.as_compat import as_messages, build_chat_model

            model = build_chat_model({
                "model_name": LLM_CONFIG["model_name"],
                "api_key": LLM_CONFIG["api_key"],
                "base_url": LLM_CONFIG["base_url"],
                "generate_kwargs": {"temperature": 0.2, "max_tokens": 1200},
            })
            nodes = []
            for h1 in doc["tree"]:
                nodes.append(h1)
                nodes.extend(h1["children"])

            def outline(level_nodes, label):
                lines = [f"- {n['id']}｜{n['title']}" for n in level_nodes]
                return "\n".join(lines)

            prompt = (
                "为下面文档目录的每一项写一句不超过40字的中文摘要，用于检索导航时判断该节是否可能包含答案。"
                "重点保留关键数字与限定条件。输出JSON：{\"summaries\": [{\"id\": \"...\", \"summary\": \"...\"}]}\n\n"
                f"文档：{doc['title']}\n{outline(nodes, '目录')}"
            )
            resp = await model(as_messages([{"role": "user", "content": prompt}]))
            data = extract_json_object(extract_llm_text(resp, ""))
            if not data:
                return
            table = {s.get("id"): s.get("summary", "") for s in data.get("summaries", [])}
            for h1 in doc["tree"]:
                if h1["id"] in table and table[h1["id"]]:
                    h1["summary"] = _clip(table[h1["id"]])
                for h2 in h1["children"]:
                    if h2["id"] in table and table[h2["id"]]:
                        h2["summary"] = _clip(table[h2["id"]])
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 摘要润色失败，保留启发式摘要：%s", exc)


def build_all(documents_dir: Path, index_dir: Path, use_llm: bool = False, only: Optional[str] = None) -> dict:
    documents_dir = Path(documents_dir)
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    built = 0
    manifest = {"schema_version": 1, "generated_at": "", "docs": []}
    old_manifest = index_dir / "manifest.json"
    if old_manifest.exists():
        try:
            manifest = json.loads(old_manifest.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            manifest = {"schema_version": 1, "generated_at": "", "docs": []}

    import datetime
    manifest["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    for path in sorted(documents_dir.glob("*.txt")):
        if only and path.stem != only:
            continue
        doc = build_doc(path, use_llm=use_llm)
        out = index_dir / f"{doc['doc_id']}.json"
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["docs"] = [d for d in manifest["docs"] if d.get("doc_id") != doc["doc_id"]]
        manifest["docs"].append({
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "summary": doc["summary"],
            "keywords": doc["keywords"],
            "source_file": doc["source_file"],
            "source_sha256": doc["source_sha256"],
            "nodes": sum(1 + len(n["children"]) for n in doc["tree"]),
        })
        built += 1
        print(f"  ✓ {path.name} -> {len(doc['tree'])} 章节 / "
              f"{sum(len(n['children']) for n in doc['tree'])} 小节")
    manifest["docs"].sort(key=lambda d: d["doc_id"])
    if not only:
        (index_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"built": built}


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 RAG 树索引")
    parser.add_argument("--doc", help="只重建指定 doc_id（如 01_travel_standards）")
    parser.add_argument("--llm", action="store_true", help="用 LLM 润色摘要（需要 API Key）")
    parser.add_argument("--no-llm", action="store_true", help="强制启发式摘要")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    base = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "ask-question"
    documents_dir = base / "data" / "documents"
    index_dir = base / "data" / "tree_index"
    use_llm = args.llm and not args.no_llm

    print("=" * 60)
    print("重建 RAG 树索引", "(LLM 摘要)" if use_llm else "(启发式摘要)")
    print("=" * 60)
    res = build_all(documents_dir, index_dir, use_llm=use_llm, only=args.doc)
    print(f"\n完成：{res['built']} 篇 → {index_dir}")
    return 0 if res["built"] else 1


if __name__ == "__main__":
    sys.exit(main())
