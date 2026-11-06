---
name: visa-info
description: Use this skill when the user asks about visa requirements, visa policies, entry requirements, or travel document information for international destinations. Triggers when user asks "去日本需要签证吗", "泰国签证怎么办", "签证材料", "免签国家", or any visa-related question. Uses VisaInfoAgent (tree-index navigation backend) to retrieve visa information from the knowledge base.
---

# Visa Information Query (签证信息查询 · 树导航版)

回答签证要求、入境政策、免签信息、办理流程等问题。与 ask-question 共用 rag_core
（树索引 + 推理导航 + BM25 兜底 + 数字逐字校验），2026-11 从向量实现迁移。

## 检索流水线

1. 树导航（规则直通 / LLM 下钻 ≤2 次）定位国家/签证类型节点；
2. BM25 词面兜底；两路合并统一打分重排取 top4；
3. 生成后金额/天数逐字校验；引用输出「文档｜章节｜小节」路径。

## Agent

- **VisaInfoAgent**（script/agent.py），model 对象 + async reply()

## 返回格式（content JSON）

- status: success / no_knowledge
- answer / proactive_question / number_check
- sources: [{file, title, path}]
- retrieved_documents / query

## 调试

```bash
python scripts/rag_query.py "日本签证能停留多久" --skill visa --full
```

## 知识库维护

- 源文档：data/documents/*.txt（日本/泰国/新加坡/免签国家，共 4 篇）
- 树索引：data/tree_index/*.json；源文档变更后重建：

```bash
python -c "import sys; from pathlib import Path; sys.path.insert(0,'.');
from rag_core.tree_builder import build_all;
build_all(Path('.claude/skills/visa-info/data/documents'), Path('.claude/skills/visa-info/data/tree_index'))"
```

- 政策类文档有时效性：索引里每篇都有「政策可能变化」提醒，生成侧保留该提示。