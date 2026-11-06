# -*- coding: utf-8 -*-
"""RAG 知识库智能体 —— 树索引 + 推理导航版（2026-11 架构升级，M3 已清理旧实现）。

检索底座：documents/*.txt → tree_index/*.json（层级树）→ LLM 导航定位节点 → 原文进 prompt。
共享实现在项目根 rag_core/ 包；ALIGO_RAG_BACKEND 仅保留配置兼容（legacy 已移除）。

对外契约（tests/test_rag_documents.py 锁定，勿改）：
- reply(x: Msg) -> Msg，content 为 JSON：status / query / answer / proactive_question /
  sources / retrieved_documents；status ∈ success / no_knowledge / document_list
- 模块级：list_documents() / _LIST_DOC_PATTERN / _POLICY_HINT / _collect_sources()
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from agentscope.message import Msg  # Msg 在 1.x/2.x 均存在

try:  # requirements 锁定 agentscope==1.0.16；2.x 移除了 AgentBase，兜底让本技能可独立运行与测试
    from agentscope.agent import AgentBase
except ImportError:  # pragma: no cover
    class AgentBase:  # 最小基类：沿用 1.x 的调用约定（__call__ -> await reply）
        def __init__(self):
            pass

        async def __call__(self, x):
            return await self.reply(x)


def _mk_msg(name: str, content: str, role: str = "assistant"):
    """跨版本构造 Msg：1.x 收字符串，2.x（pydantic）要求 content 为块列表。"""
    try:
        return Msg(name=name, content=content, role=role)
    except Exception:  # pragma: no cover - agentscope 2.x
        return Msg(name=name, content=[{"type": "text", "text": content}], role=role)

from cache.decorators import cached

logger = logging.getLogger(__name__)

# ── 旧版保留：知识库文档清单与政策提示正则（测试锁定） ────────────
_DOC_DIR = Path(__file__).resolve().parent.parent / "data" / "documents"
_LIST_DOC_PATTERN = re.compile(
    r"(?:(?:有哪些|有什么|多少|列出|清单|列表|目录).{0,8}(?:知识库|文档|资料|文件))"
    r"|(?:(?:知识库|文档库|资料库).{0,8}(?:有哪些|包含|覆盖|清单|列表|目录))"
    r"|^(?:知识库|文档列表)$"
)
_POLICY_HINT = re.compile(r"标准|政策|规定|额度|上限|报销|补贴|协议|优惠|折扣|审批|怎么报|能报")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def list_documents() -> List[Dict]:
    """列出知识库里的原始文档（文件名 / 标题 / 字数）。"""
    docs = []
    if not _DOC_DIR.is_dir():
        return docs
    for p in sorted(_DOC_DIR.glob("*.txt")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        docs.append({"file": p.name, "title": _first_line(text) or p.stem, "chars": len(text)})
    return docs


def _collect_sources(docs: List[Dict]) -> List[Dict]:
    """从检索结果按文档去重，得到「引用来源」。兼容旧版 metadata 结构。"""
    seen, out = set(), []
    for d in docs:
        md = d.get("metadata") or {}
        fname = md.get("parent_doc") or md.get("file") or ""
        if not fname or fname in seen:
            continue
        seen.add(fname)
        out.append({"file": fname, "title": (md.get("title") or fname).split(" (Part")[0]})
    return out


# ── 懒加载组件 ──────────────────────────────────────────────
_tree_store = None
_bm25 = None


def _get_tree_store():
    global _tree_store
    if _tree_store is None:
        from rag_core.tree_store import TreeStore
        _tree_store = TreeStore()
        if not _tree_store.load():
            logger.error("树索引加载失败：%s", _tree_store.errors[:3])
    return _tree_store


def _get_bm25():
    global _bm25
    if _bm25 is None:
        from rag_core.bm25_fallback import BM25Fallback
        _bm25 = BM25Fallback(_get_tree_store())
    return _bm25


def _reset_components() -> None:
    """测试钩子：丢弃缓存组件（改树/改配置后重建）。"""
    global _tree_store, _bm25
    _tree_store = None
    _bm25 = None


def _hits_to_docs(hits) -> List[Dict]:
    """导航命中 → 生成用文档块（含 file/path/lines 便于引用）。"""
    store = _get_tree_store()
    out, seen = [], set()
    for h in hits:
        key = (h.doc_id, h.node_id)
        if key in seen:
            continue
        seen.add(key)
        text = store.node_text(h.doc_id, h.node_id)
        if not text:
            continue
        doc = store.docs.get(h.doc_id)
        node = doc.find(h.node_id) if doc else None
        out.append({
            "doc_id": h.doc_id,
            "node_id": h.node_id,
            "file": Path(doc.source_file).name if doc else f"{h.doc_id}.txt",
            "path": h.path or store.path_of(h.doc_id, h.node_id),
            "text": text,
            "lines": node.line_range if node else None,
        })
    return out


class RAGKnowledgeAgent(AgentBase):
    """RAG 知识库智能体（树导航版）"""

    def __init__(
        self,
        name: str = "RAGKnowledgeAgent",
        model=None,
        knowledge_base_path: str = None,
        collection_name: str = "business_travel_knowledge",  # 兼容旧签名，不再使用
        top_k: int = 3,
        **kwargs,
    ):
        super().__init__()
        self.name = name
        self.model = model
        self.top_k = top_k
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()
        try:
            from config import RAG_CONFIG
            self._nav_max_calls = int(RAG_CONFIG.get("nav_max_llm_calls", 2))
            self._nav_floor = float(RAG_CONFIG.get("nav_confidence_floor", 0.6))
            self._nav_timeout = float(RAG_CONFIG.get("nav_timeout_sec", 12.0))
            self._nav_use_llm = bool(RAG_CONFIG.get("nav_use_llm", True))
            self.top_k = int(RAG_CONFIG.get("top_k", 4))
        except Exception:  # noqa: BLE001
            self._nav_max_calls, self._nav_floor, self._nav_timeout = 2, 0.6, 12.0
        self._navigator = None
        self._answerer = None
        self.initialized = True
        logger.info("RAGKnowledgeAgent（树导航版）初始化完成")

    # ── 组件 ────────────────────────────────────────────────
    def _get_navigator(self):
        if self._navigator is None:
            from rag_core.navigator import Navigator
            self._navigator = Navigator(
                _get_tree_store(), model=self.model,
                max_llm_calls=self._nav_max_calls,
                confidence_floor=self._nav_floor,
                timeout=self._nav_timeout,
                use_llm=getattr(self, "_nav_use_llm", True),
            )
        return self._navigator

    def _get_answerer(self):
        if self._answerer is None:
            from rag_core.answerer import Answerer
            instruction = ""
            try:
                instruction = self.skill_loader.get_skill_content("ask-question") or ""
            except Exception:  # noqa: BLE001
                pass
            self._answerer = Answerer(model=self.model, skill_instruction=instruction)
        return self._answerer

    # ── 检索（生产入口，评测复用） ─────────────────────────────
    async def retrieve(self, query: str, top_k: Optional[int] = None) -> List[Dict]:
        """导航命中 ∪ BM25 候选 → 去重 → 按 BM25 重排 → top_k。

        理由：树导航负责「定位章节」，BM25 负责「在候选人里按词面证据排序」，
        二者并集再重排，单路失灵时另一路仍能兜住（离线评测即测此路径）。
        """
        k = top_k or self.top_k
        store = _get_tree_store()
        meta = {"mode": "nav", "calls": 0, "degraded": False, "nav_hits": 0, "bm25_hits": 0}
        merged: Dict[tuple, Dict] = {}
        try:
            if store.loaded:
                nav = await self._get_navigator().navigate(query)
                meta.update(calls=nav.llm_calls, degraded=nav.degraded,
                            ms=nav.elapsed_ms, reason=nav.reason)
                for d in _hits_to_docs(nav.hits):
                    merged[(d["doc_id"], d["node_id"])] = d
                meta["nav_hits"] = len(merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning("树导航异常，转 BM25：%s", exc)
            meta.update(degraded=True, reason=f"error:{exc}")

        nav_keys = set(merged)
        for d in self._bm25_docs(query, top_k=max(4, k + 2)):
            merged.setdefault((d["doc_id"], d["node_id"]), d)
        meta["bm25_hits"] = len(merged) - meta["nav_hits"]

        # 统一打分：所有候选都按 BM25 打分（导航命中加 25% 权重，保留结构信号）
        try:
            scores = _get_bm25().scores_for(query, list(merged))
        except Exception:  # noqa: BLE001
            scores = {}
        top_score = max(scores.values()) if scores else 0.0
        for key, d in merged.items():
            base = scores.get(key, 0.0)
            norm = (base / top_score) if top_score > 0 else 0.0
            d["score"] = round(norm + (0.6 if key in nav_keys else 0.0), 4)

        # 祖先优先：父章节入选时，其子孙节点不再单列（父章节原文已覆盖，避免挤占 top_k）
        all_keys = set(merged)
        def _has_ancestor(key) -> bool:
            doc_id, node_id = key
            parts = node_id.split("#")
            for i in range(1, len(parts)):
                if (doc_id, "#".join(parts[:i])) in all_keys:
                    return True
            return False
        survivors = [d for k, d in merged.items() if not _has_ancestor(k)]
        if not survivors:
            survivors = list(merged.values())

        docs = survivors
        docs.sort(key=lambda d: -float(d.get("score", 0.0)))
        meta["ancestor_pruned"] = len(merged) - len(survivors)
        self._last_retrieval = meta
        logger.info("检索：nav=%d bm25=+%d 取 %d | %s",
                    meta["nav_hits"], max(meta["bm25_hits"], 0), min(k, len(docs)), meta)
        return docs[:k]

    # ── 主流程 ──────────────────────────────────────────────
    @cached("rag_knowledge", ttl=3600)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if not self.initialized:
            return self._err("RAG Agent not initialized")
        if x is None:
            return _mk_msg(self.name, json.dumps({}))

        content = x[-1].content if isinstance(x, list) else x.content
        user_query = self._extract_query(content)

        # 0) 清单类问题 → 直接列文档
        if _LIST_DOC_PATTERN.search(user_query) and not _POLICY_HINT.search(user_query):
            return self._document_list_reply(user_query)

        # 1) 检索：树导航 ∪ BM25 → 合并去重 → 按 BM25 重排 → top_k=4
        # （4 个节点 ≈ 2000 字 ≈ 1400 token，SCENARIO_TOKENS rag=2048 之内；
        #   离线评测 Hit@4=0.975 vs Hit@3=0.90，多一个槽位显著提覆盖）
        docs = await self.retrieve(user_query, top_k=4)
        nav_meta = self._last_retrieval
        if not docs:
            return self._no_knowledge(user_query)

        # 2) 生成 + 数字逐字校验
        num_check = "skipped"
        answer, proactive = "", ""
        cited = docs
        if self.model:
            ans = await self._get_answerer().generate(user_query, docs)
            answer, proactive, num_check = ans.answer, ans.proactive_question, ans.number_check
            if ans.used_ids:
                cited = [d for d in docs if d["node_id"] in ans.used_ids] or docs
            if not answer:
                answer = "知识库中找到了相关条款，但生成答案时出错，请稍后重试。"
        else:
            answer = "以下是知识库中的相关条款：\n\n" + "\n\n".join(
                f"【{d['path']}】\n{d['text']}" for d in docs)

        # 3) 引用：只列模型实际用到的节点（used），避免「答对了但引用的是别的条款」
        import re as _re
        answer = _re.sub(r"\n*依据：[^\n]*$", "", answer.rstrip()).rstrip()  # 剥掉模型自带的一行，统一用规范引用
        sources = self._sources(cited)
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
                 "metadata": {"parent_doc": d["file"], "title": d["path"],
                              "path": d["path"], "lines": d["lines"]}}
                for d in docs
            ],
            "retrieval": nav_meta,
        }
        return _mk_msg(self.name, json.dumps(result, ensure_ascii=False))

    # ── 兼容旧接口 ──────────────────────────────────────────
    def search_knowledge(self, query: str, top_k: Optional[int] = None) -> List[Dict]:
        """兼容旧同步检索入口：返回 BM25 命中（不再走向量）。"""
        k = top_k or self.top_k
        return [
            {"id": r["node_id"], "content": r["text"],
             "metadata": {"title": r["path"]}, "distance": round(1.0 - min(r["score"], 1.0), 4)}
            for r in _get_bm25().search(query, top_k=k)
        ]

    def get_stats(self) -> Dict:
        try:
            st = _get_tree_store().stats()
            return {"status": "success", "collection_name": "tree_index",
                    "total_documents": st["documents"], "nodes": st["nodes"],
                    "leaves": st["leaves"], "stale": st["stale"],
                    "knowledge_base_path": st["index_dir"]}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def close(self):
        pass

    def __del__(self):
        pass

    # ── 私有 ────────────────────────────────────────────────
    @staticmethod
    def _sources(docs: List[Dict]) -> List[Dict]:
        seen, out = set(), []
        for d in docs:
            key = (d["file"], d["path"])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "file": d["file"],
                "title": (d["path"].split("｜")[0] if d["path"] else d["file"]),
                "path": d["path"],
                "lines": d["lines"],
            })
        return out

    def _bm25_docs(self, query: str, top_k: int = 5) -> List[Dict]:
        try:
            fallback = _get_bm25()
        except Exception as exc:  # noqa: BLE001
            logger.warning("BM25 兜底不可用：%s", exc)
            return []
        store = _get_tree_store()
        out = []
        for r in fallback.search(query, top_k=top_k):
            doc = store.docs.get(r["doc_id"])
            node = doc.find(r["node_id"]) if doc else None
            out.append({
                "doc_id": r["doc_id"],
                "node_id": r["node_id"],
                "file": Path(doc.source_file).name if doc else f"{r['doc_id']}.txt",
                "path": r["path"], "text": r["text"],
                "lines": node.line_range if node else None,
                "score": r["score"],
            })
        return out

    def _extract_query(self, content) -> str:
        if isinstance(content, list):  # agentscope 2.x：content 为块列表
            parts = []
            for b in content:
                t = b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
                if t:
                    parts.append(t)
            content = "\n".join(parts)
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    ctx = data.get("context")
                    if isinstance(ctx, dict) and ctx.get("rewritten_query"):
                        return ctx["rewritten_query"]
                    if data.get("rewritten_query"):
                        return data["rewritten_query"]
            except Exception:  # noqa: BLE001
                pass
        return content if isinstance(content, str) else str(content)

    def _document_list_reply(self, query: str) -> Msg:
        docs = list_documents()
        lines = [f"知识库共 {len(docs)} 份文档：", ""]
        for i, d in enumerate(docs, 1):
            lines.append(f"{i}. {d['title']}（{d['file']}，约 {d['chars'] // 1000}k 字）")
        result = {"status": "document_list", "query": query, "answer": "\n".join(lines),
                  "documents": docs, "proactive_question": "需要我帮你查具体条款吗？"}
        return _mk_msg(self.name, json.dumps(result, ensure_ascii=False))

    def _no_knowledge(self, query: str) -> Msg:
        result = {"status": "no_knowledge", "query": query,
                  "answer": "抱歉，我在知识库中没有找到相关信息。", "retrieved_documents": []}
        return _mk_msg(self.name, json.dumps(result, ensure_ascii=False))

    def _err(self, message: str) -> Msg:
        return Msg(name=self.name, content=json.dumps(
            {"status": "error", "message": message}, ensure_ascii=False), role="assistant")