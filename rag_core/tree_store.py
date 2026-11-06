# -*- coding: utf-8 -*-
"""文档树索引的加载与校验（tree_store）。

设计要点（见 docs/rag-tree-architecture-dev-plan.md §5、§6.2）：
- 树文件只存「结构与摘要」，正文一律按 line_range 从源 txt 实时切片，避免两份事实；
- 加载时强制校验：字段齐全 / id 唯一 / 行号不越界 / 源文件 hash 一致；
- 源文件变了但树没重建 → 该篇标记 stale，运行时自动降级，不用过期答案。
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class Node:
    doc_id: str
    id: str
    title: str
    summary: str
    line_range: List[int]
    level: int = 1
    children: List["Node"] = field(default_factory=list)

    def is_leaf(self) -> bool:
        return not self.children


@dataclass
class DocTree:
    doc_id: str
    title: str
    summary: str
    source_file: str
    source_sha256: str
    keywords: List[str]
    tree: List[Node]
    stale: bool = False
    schema_version: int = SCHEMA_VERSION

    def nodes(self) -> List[Node]:
        out: List[Node] = []

        def walk(ns: List[Node]):
            for n in ns:
                out.append(n)
                walk(n.children)
        walk(self.tree)
        return out

    def leaves(self) -> List[Node]:
        return [n for n in self.nodes() if n.is_leaf()]

    def find(self, node_id: str) -> Optional[Node]:
        for n in self.nodes():
            if n.id == node_id:
                return n
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class TreeStore:
    """加载 tree_index/*.json，提供节点原文切片。"""

    def __init__(self, index_dir: Optional[Path] = None, documents_dir: Optional[Path] = None):
        base = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "ask-question"
        self.index_dir = Path(index_dir) if index_dir else base / "data" / "tree_index"
        self.documents_dir = Path(documents_dir) if documents_dir else base / "data" / "documents"
        self.docs: Dict[str, DocTree] = {}
        self._lines_cache: Dict[str, List[str]] = {}
        self.errors: List[str] = []
        self.loaded = False

    # ── 加载 ────────────────────────────────────────────────
    def load(self, auto_build: bool = True) -> bool:
        self.docs, self.errors = {}, []
        files = sorted(self.index_dir.glob("*.json")) if self.index_dir.is_dir() else []
        files = [f for f in files if f.name != "manifest.json"]

        if (not files or self._is_stale(files)) and auto_build:
            if self.build():
                files = [f for f in sorted(self.index_dir.glob("*.json")) if f.name != "manifest.json"]

        for f in files:
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{f.name}: JSON 解析失败 {exc}")
                continue
            doc, errs = self._parse_doc(raw)
            if errs:
                self.errors.extend(errs)
                if doc is None:
                    continue
            if doc is not None:
                self.docs[doc.doc_id] = doc

        self.loaded = bool(self.docs)
        if not self.loaded:
            logger.error("TreeStore 加载失败：%s", "; ".join(self.errors[:3]) or "树索引为空")
        return self.loaded

    def build(self) -> bool:
        """首次运行或源文档变更时自动建树（纯解析，不联网）。"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("tree_builder", Path(__file__).with_name("tree_builder.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            res = mod.build_all(documents_dir=self.documents_dir, index_dir=self.index_dir)
            logger.info("tree_index 已重建：%s 篇", res.get("built", 0))
            return bool(res.get("built"))
        except Exception as exc:  # noqa: BLE001
            logger.error("自动建树失败：%s", exc)
            return False

    def _is_stale(self, files: List[Path]) -> bool:
        for f in files:
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                src = self.documents_dir / Path(raw.get("source_file", "")).name
                if src.exists() and sha256_file(src) != raw.get("source_sha256"):
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False

    def _parse_doc(self, raw: dict) -> Tuple[Optional[DocTree], List[str]]:
        errs: List[str] = []
        doc_id = raw.get("doc_id")
        if not doc_id:
            return None, ["缺少 doc_id"]
        src = self._source_path(raw.get("source_file", doc_id))
        if src is None or not src.exists():
            return None, [f"{doc_id}: 源文档不存在 {raw.get('source_file')}"]

        lines = self._source_lines(doc_id, src)
        tree = [self._to_node(doc_id, n, 1, len(lines), errs) for n in raw.get("tree", [])]
        doc = DocTree(
            doc_id=doc_id,
            title=raw.get("title", doc_id),
            summary=raw.get("summary", ""),
            source_file=Path(src).name,
            source_sha256=raw.get("source_sha256", ""),
            keywords=list(raw.get("keywords", [])),
            tree=tree,
            stale=(sha256_file(src) != raw.get("source_sha256", "")),
            schema_version=int(raw.get("schema_version", 1)),
        )
        if doc.stale:
            errs.append(f"{doc_id}: 源文档已变更，树索引过期（请重跑 tree_builder.py）")
        seen = set()
        for n in doc.nodes():
            if n.id in seen:
                errs.append(f"{doc_id}: 节点 id 重复 {n.id}")
            seen.add(n.id)
        return doc, errs

    def _to_node(self, doc_id: str, raw: dict, level: int, total_lines: int, errs: List[str]) -> Node:
        rng = raw.get("line_range") or [1, 1]
        try:
            start, end = int(rng[0]), int(rng[1])
        except Exception:  # noqa: BLE001
            start, end = 1, 1
        if start < 1 or end < start or end > total_lines + 1:
            errs.append(f"{doc_id}: 节点 {raw.get('id')} 行号越界 {rng}（文档 {total_lines} 行）")
            start, end = max(1, min(start, total_lines)), max(start, min(end, total_lines))
        node = Node(
            doc_id=doc_id,
            id=raw.get("id", f"{doc_id}#n"),
            title=raw.get("title", ""),
            summary=raw.get("summary", ""),
            line_range=[start, end],
            level=level,
        )
        node.children = [self._to_node(doc_id, c, level + 1, total_lines, errs) for c in raw.get("children", [])]
        return node

    # ── 查询接口 ────────────────────────────────────────────
    def _source_path(self, source_file: str) -> Optional[Path]:
        if not source_file:
            return None
        p = Path(source_file)
        cand = self.documents_dir / p.name
        return cand if cand.exists() else None

    def _source_lines(self, doc_id: str, path: Path) -> List[str]:
        if doc_id not in self._lines_cache:
            self._lines_cache[doc_id] = path.read_text(encoding="utf-8").split("\n")
        return self._lines_cache[doc_id]

    def node_text(self, doc_id: str, node_id: str) -> str:
        doc = self.docs.get(doc_id)
        if not doc:
            return ""
        node = doc.find(node_id)
        if not node:
            return ""
        return self._slice(doc_id, node.line_range)

    def _slice(self, doc_id: str, rng: List[int]) -> str:
        src = self._source_path(self.docs[doc_id].source_file)
        if src is None:
            return ""
        lines = self._source_lines(doc_id, src)
        start = max(1, int(rng[0]))
        end = min(len(lines), int(rng[1]))
        body = "\n".join(lines[start - 1:end]).strip()
        return re_strip(body)

    def path_of(self, doc_id: str, node_id: str) -> str:
        """返回「文档标题｜章节｜小节」路径（去掉标题自带的【】外壳）。"""
        doc = self.docs.get(doc_id)
        if not doc:
            return ""
        chain: List[str] = []

        def walk(ns: List[Node], trail: List[str]) -> bool:
            for n in ns:
                t = trail + [n.title]
                if n.id == node_id:
                    chain.extend(t)
                    return True
                if walk(n.children, t):
                    return True
            return False
        walk(doc.tree, [doc.title.strip("【】")])
        return "｜".join(chain)

    def manifest_cards(self) -> List[dict]:
        return [
            {"doc_id": d.doc_id, "title": d.title, "summary": d.summary, "keywords": d.keywords}
            for d in sorted(self.docs.values(), key=lambda x: x.doc_id)
            if not d.stale
        ]

    def stats(self) -> dict:
        return {
            "documents": len(self.docs),
            "nodes": sum(len(d.nodes()) for d in self.docs.values()),
            "leaves": sum(len(d.leaves()) for d in self.docs.values()),
            "stale": [d.doc_id for d in self.docs.values() if d.stale],
            "index_dir": str(self.index_dir),
        }

    def maybe_reload(self) -> None:
        """源文档或树文件变动时热重载（长期运行进程用）。"""
        mt = [(self.index_dir / f.name).stat().st_mtime for f in self.index_dir.glob("*.json")] if self.index_dir.is_dir() else []
        sig = (len(mt), max(mt) if mt else 0)
        if getattr(self, "_sig", None) != sig:
            self._sig = sig
            if self.docs:
                self.load(auto_build=False)


def re_strip(text: str) -> str:
    """去掉整段末尾的空白，保留内部缩进结构。"""
    lines = [l.rstrip() for l in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)