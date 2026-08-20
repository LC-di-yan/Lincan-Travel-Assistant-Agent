---
name: visa-info
description: Use this skill when the user asks about visa requirements, visa policies, entry requirements, or travel document information for international destinations. Triggers when user asks "去日本需要签证吗", "泰国签证怎么办", "签证材料", "免签国家", or any visa-related question. Uses VisaInfoAgent with RAG to retrieve visa information from the knowledge base.
---

# Visa Information Query (签证信息查询)

回答用户关于签证要求、入境政策、免签信息、签证办理流程等问题，使用 **VisaInfoAgent** 从签证知识库检索并生成答案。

## When to Use

- 用户问「去XX需要签证吗」「签证怎么办」「免签国家有哪些」等
- 涉及出入境、护照、签证材料、办理时间等问题

## Agent

- **VisaInfoAgent** (`script/agent.py`)
- 使用 RAG 管线（Milvus Lite + sentence-transformers）
- **异步**：`reply()` 为 `async`，需 `await`

## 返回格式

- `status`: `"success"` 或 `"no_knowledge"`
- `answer`: 自然语言答案
- `retrieved_documents`: 列表，每项含 `content`, `metadata`
- `query`: 用户问题

## 知识库

- 签证知识文档：`data/documents/`
- 涵盖：热门目的地签证政策、免签/落地签国家、签证材料清单、办理流程
