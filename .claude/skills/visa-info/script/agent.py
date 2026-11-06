# -*- coding: utf-8 -*-
"""签证信息智能体 VisaInfoAgent（树导航版，2026-11 迁移）。

与 ask-question 共用 rag_core（树索引 + 推理导航 + BM25 兜底 + 数字校验），
差异只在知识库目录（data/documents → data/tree_index）与生成 prompt。
旧向量实现已删除（原 Milvus Lite + bge，见 docs/rag-tree-architecture-dev-plan.md）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from agentscope.message import Msg

try:  # requirements 锁定 agentscope==1.0.16；2.x 兜底保证本技能可独立运行/测试
    from agentscope.agent import AgentBase
except ImportError:  # pragma: no cover
    class AgentBase:
        def __init__(self):
            pass

        async def __call__(self, x):
            return await self.reply(x)

from cache.decorators import cached
from rag_core.tree_store import TreeStore
from rag_core.navigator import Navigator
from rag_core.bm25_fallback import BM25Fallback
from rag_core.answerer import Answerer

logger = logging.getLogger(__name__)

_SKILL_DIR = Path(__file__).resolve().parent.parent
_DOC_DIR = _SKILL_DIR / "data" / "documents"
_INDEX_DIR = _SKILL_DIR / "data" / "tree_index"

_store: Optional[TreeStore] = None
_bm25: Optional[BM25Fallback] = None

PROMPT_SYSTEM = "你是签证政策顾问，简洁回答。"
NO_KNOWLEDGE_HINT = "抱歉，签证知识库中没有找到相关信息。建议查阅目的地国家的大使馆官网获取最新签证政策。"


def _get_store() -> TreeStore:
    global _store
    if _store is None:
        _store = TreeStore(index_dir=_INDEX_DIR, documents_dir=_DOC_DIR)
        _store.load()
    return _store


def _get_bm25() -> BM25Fallback:
    global _bm25
    if _bm25 is None:
        _bm25 = BM25Fallback(_get_store())
    return _bm25


def _mk_msg(name: str, content: str, role: str = "assistant"):
    """跨版本构造 Msg：1.x 收字符串，2.x（pydantic）要求块列表。"""
    try:
        return Msg(name=name, content=content, role=role)
    except Exception:  # pragma: no cover
        return Msg(name=name, content=[{"type": "text", "text": content}], role=role)


class VisaInfoAgent(AgentBase):
    """签证信息智能体（树导航版）"""

    def __init__(self, name: str = "VisaInfoAgent", model=None, top_k: int = 4, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.top_k = top_k
        self.initialized = True
        logger.info("VisaInfoAgent（树导航版）初始化完成")

    async def retrieve(self, query: str, top_k: Optional[int] = None) -> List[Dict]:
        """导航 ∪ BM25 → 统一打分 → 祖先去冗余 → top_k。"""
        k = top_k or self.top_k
        store = _get_store()
        if not store.loaded:
            return []
        merged: Dict[tuple, Dict] = {}
        meta = {"mode": "nav", "calls": 0, "degraded": False, "nav_hits": 0, "bm25_hits": 0}
        nav = Navigator(store, model=self.model)
        try:
            res = await nav.navigate(query)
            meta.update(calls=res.llm_calls, degraded=res.degraded, ms=res.elapsed_ms)
            for h in res.hits:
                text = store.node_text(h.doc_id, h.node_id)
                node = store.docs[h.doc_id].find(h.node_id)
                if text:
                    merged[(h.doc_id, h.node_id)] = {
                        "doc_id": h.doc_id, "node_id": h.node_id,
                        "file": store.docs[h.doc_id].source_file,
                        "path": h.path, "text": text,
                        "lines": node.line_range if node else None,
                    }
            meta["nav_hits"] = len(merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning("签证树导航异常：%s", exc)

        for r in _get_bm25().search(query, top_k=max(4, k + 2)):
            node = store.docs[r["doc_id"]].find(r["node_id"])
            merged.setdefault((r["doc_id"], r["node_id"]), {
                "doc_id": r["doc_id"], "node_id": r["node_id"],
                "file": store.docs[r["doc_id"]].source_file,
                "path": r["path"], "text": r["text"],
                "lines": node.line_range if node else None,
                "score": r["score"],
            })

        scores = _get_bm25().scores_for(query, list(merged))
        top_score = max(scores.values()) if scores else 0.0
        nav_keys = {k for k in merged if "score" not in merged[k]}
        for key, d in merged.items():
            base = scores.get(key, 0.0)
            norm = (base / top_score) if top_score > 0 else 0.0
            d["score"] = round(norm + (0.6 if key in nav_keys else 0.0), 4)

        def _has_ancestor(key) -> bool:
            doc_id, node_id = key
            parts = node_id.split("#")
            return any((doc_id, "#".join(parts[:i])) in merged for i in range(1, len(parts)))

        docs = [d for k, d in merged.items() if not _has_ancestor(k)] or list(merged.values())
        docs.sort(key=lambda d: -float(d["score"]))
        meta["bm25_hits"] = len(merged) - meta["nav_hits"]
        meta["ancestor_pruned"] = len(merged) - len(docs)
        self._last_retrieval = meta
        return docs[:k]

    @cached("visa_info", ttl=21600)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        """签证问答主流程（对外契约与旧版一致）"""
        if x is None:
            return _mk_msg(self.name, json.dumps({}))

        content = x[-1].content if isinstance(x, list) else x.content
        if isinstance(content, list):  # agentscope 2.x 块列表
            content = "\n".join(
                b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
                for b in content if b)
        user_query = content
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    ctx = data.get("context")
                    if isinstance(ctx, dict) and ctx.get("rewritten_query"):
                        user_query = ctx["rewritten_query"]
                    elif data.get("rewritten_query"):
                        user_query = data["rewritten_query"]
            except Exception:  # noqa: BLE001
                pass

        docs = await self.retrieve(user_query)
        if not docs:
            return _mk_msg(self.name, json.dumps({
                "status": "no_knowledge", "query": user_query,
                "answer": NO_KNOWLEDGE_HINT, "retrieved_documents": []}, ensure_ascii=False))

        num_check, answer, proactive = "skipped", "", ""
        cited = docs
        if self.model:
            ans = Answerer(model=self.model, skill_instruction=(
                "你是签证政策顾问。签证政策可能变化，回答末尾提醒用户出行前确认最新信息。"),
                system=PROMPT_SYSTEM)
            res = await ans.generate(user_query, docs)
            answer, proactive, num_check = res.answer, res.proactive_question, res.number_check
            if res.used_ids:
                cited = [d for d in docs if d["node_id"] in res.used_ids] or docs
            if not answer:
                answer = "签证知识库中找到了相关条款，但生成答案时出错，请稍后重试。"
        else:
            answer = "以下是签证知识库中的相关条款：\n\n" + "\n\n".join(
                f"【{d['path']}】\n{d['text']}" for d in docs)

        seen, sources = set(), []
        for d in cited:
            key = (d["file"], d["path"])
            if key in seen:
                continue
            seen.add(key)
            sources.append({"file": d["file"], "title": d["path"].split("｜")[0], "path": d["path"]})
        cite = "、".join(f"《{s['path']}》" for s in sources[:3])
        if cite and cite not in answer:
            answer = answer.rstrip() + f"\n\n依据：{cite}"

        result = {
            "status": "success",
            "query": user_query,
            "answer": answer,
            "proactive_question": proactive,
            "number_check": num_check,
            "sources": sources,
            "retrieved_documents": [
                {"content": d["text"][:200] + ("..." if len(d["text"]) > 200 else ""),
                 "metadata": {"parent_doc": d["file"], "title": d["path"], "path": d["path"]}}
                for d in docs
            ],
        }
        return _mk_msg(self.name, json.dumps(result, ensure_ascii=False))

    def search_knowledge(self, query: str, top_k: Optional[int] = None) -> List[Dict]:
        """兼容旧同步检索入口。"""
        return [
            {"id": r["node_id"], "content": r["text"],
             "metadata": {"title": r["path"]}, "distance": round(1.0 - min(r["score"], 1.0), 4)}
            for r in _get_bm25().search(query, top_k=top_k or self.top_k)
        ]

    def get_stats(self) -> Dict:
        st = _get_store().stats()
        return {"status": "success", "collection_name": "visa_tree_index",
                "total_documents": st["documents"], "nodes": st["nodes"],
                "knowledge_base_path": st["index_dir"]}

    def close(self):
        pass

    def __del__(self):
        pass