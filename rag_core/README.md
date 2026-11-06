# rag_core — 共享 RAG 核

ask-question（差旅政策）与 visa-info（签证政策）共用的检索实现。
设计文档：[docs/rag-tree-architecture-dev-plan.md](../docs/rag-tree-architecture-dev-plan.md)

## 模块

| 文件 | 职责 | 主要接口 |
|---|---|---|
| tree_store.py | 加载/校验树索引，按 line_range 切片原文 | `TreeStore(index_dir, documents_dir).load()` → `node_text()` / `path_of()` |
| tree_builder.py | 解析文档标题层级 → 生成树 JSON + manifest | `build_all(documents_dir, index_dir, use_llm=False)` |
| navigator.py | 文档路由 + 节点下钻（规则 / LLM） | `Navigator(store, model).navigate(query)` |
| bm25_fallback.py | 全节点词面检索与打分 | `search(query, top_k)` / `scores_for(query, keys)` |
| answerer.py | 生成答案 + 数字逐字校验 | `Answerer(model).generate(query, docs)` / `verify_numbers()` |

## 接入一个新知识库（三步）

1. 准备 `data/documents/*.txt`（用「一、」「1.」「Q1:」这类自带层级来写）；
2. `python scripts/build_rag_index.py`（或对目录直接调 `build_all`）；
3. 复制任一现有技能的 `agent.py`，改 `_DOC_DIR` / `_INDEX_DIR` 与 system prompt。

## 测试

```bash
python -m pytest tests/test_tree_builder.py tests/test_navigator.py \
                 tests/test_bm25_fallback.py tests/test_answerer_validation.py -q
```