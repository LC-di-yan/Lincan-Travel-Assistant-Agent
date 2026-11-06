# -*- coding: utf-8 -*-
"""BM25 词面兜底检索（bm25_fallback）。

角色（见方案 §6.4）：
1. 树导航降级时的兜底主路；
2. no_knowledge 前的最后一搏（替代旧版「往 query 后拼关键词」的二次检索 hack）。

索引对象 = 全部叶子节点原文（~324 段，内存 <1ms/查询），不依赖任何网络。
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import jieba
    jieba.setLogLevel(60)
    from rank_bm25 import BM25Okapi
    _BM25_OK = True
except ImportError as _e:  # pragma: no cover
    logger.warning("jieba/rank-bm25 未安装，BM25 兜底不可用：%s", _e)
    _BM25_OK = False


def _normalize(t: str) -> str:
    return re.sub(r"\s+", " ", t)


class BM25Fallback:
    """全库叶子节点的 BM25 索引。线程内单例由 agent 持有。"""

    def __init__(self, tree_store):
        self.store = tree_store
        self._ids: List[str] = []
        self._pos: Dict[tuple, int] = {}
        self._bm25 = None
        self._built_sig = None
        self._build()

    @staticmethod
    def _tokenize(text: str, title: str = "") -> List[str]:
        """jieba 词 ∪ 字符 bigram；标题 token 重复 3 次加权（标题是导航强信号）。"""
        norm = _normalize(text)
        toks = [t for t in jieba.lcut(norm) if t.strip()]
        toks += [t for t in jieba.lcut(_normalize(title)) for _ in range(2)]
        compact = re.sub(r"[\s/、，。：:；;（）()\[\]｜|-]", "", norm)
        toks += [compact[i:i + 2] for i in range(len(compact) - 1)]
        return toks

    def _build(self) -> None:
        if not _BM25_OK:
            return
        ids: List[str] = []
        docs: List[List[str]] = []
        for doc_id, doc in sorted(self.store.docs.items()):
            if doc.stale:
                continue
            for node in doc.nodes():
                text = self.store.node_text(doc_id, node.id)
                if not text:
                    continue
                ids.append(f"{doc_id}::{node.id}")
                self._pos[(doc_id, node.id)] = len(ids) - 1
                docs.append(self._tokenize(text, node.title))
        if not docs:
            logger.warning("BM25 索引为空（树未加载或全部过期）")
            return
        self._ids = ids
        self._bm25 = BM25Okapi(docs)
        self._built_sig = tuple(sorted(self.store.docs))
        logger.info("BM25 兜底索引构建完成：%d 段", len(ids))

    def _ensure(self) -> None:
        if _BM25_OK and self._bm25 is None:
            self._build()

    def scores_for(self, query: str, keys) -> Dict[tuple, float]:
        """给指定节点集合打分（用于把导航命中并入 BM25 排序）。"""
        self._ensure()
        if self._bm25 is None or not _BM25_OK:
            return {}
        all_scores = self._bm25.get_scores(self._tokenize(query))
        return {k: float(all_scores[self._pos[k]]) for k in keys if k in self._pos}

    def search(self, query: str, top_k: int = 5) -> List[dict]:
        """返回 [{doc_id, node_id, score, text}]，按相关性降序。"""
        self._ensure()
        if self._bm25 is None or not _BM25_OK:
            return []
        tokens = self._tokenize(query)
        scores = self._bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        out: List[dict] = []
        for i in order:
            if scores[i] <= 0:
                continue
            doc_id, node_id = self._ids[i].split("::", 1)
            out.append({
                "doc_id": doc_id,
                "node_id": node_id,
                "score": round(float(scores[i]), 3),
                "text": self.store.node_text(doc_id, node_id),
                "path": self.store.path_of(doc_id, node_id),
            })
        return out
