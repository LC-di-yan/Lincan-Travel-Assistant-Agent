# -*- coding: utf-8 -*-
"""共享 RAG 核：文档树索引 + 导航 + BM25 兜底 + 答案生成与数字校验。

ask-question（差旅政策）与 visa-info（签证政策）共用同一实现，
差异只在 documents_dir / index_dir / 生成 prompt。
"""
from .tree_store import TreeStore, DocTree, Node
from .navigator import Navigator, NavResult, NavHit
from .bm25_fallback import BM25Fallback
from .answerer import Answerer, AnswerResult, verify_numbers

__all__ = [
    "TreeStore", "DocTree", "Node",
    "Navigator", "NavResult", "NavHit",
    "BM25Fallback",
    "Answerer", "AnswerResult", "verify_numbers",
]
