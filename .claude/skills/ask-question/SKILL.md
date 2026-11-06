---
name: ask-question
description: Use this skill when the user asks questions about travel policies, reimbursement, booking guides, city information, or any travel-related questions. This skill uses RAGKnowledgeAgent (tree-index navigation backend) to retrieve answers from the knowledge base.
---

# Ask Travel Question (RAG 知识库问答 · 树导航版)

回答用户关于差旅政策、报销、预订、城市指南等问题。检索底座为「文档树索引 + 推理导航 + BM25 词面兜底」
（2026-11 架构升级，详见 docs/rag-tree-architecture-dev-plan.md）。

## 检索流水线

1. 树导航：规则直通（标题/关键词命中）→ LLM 逐层下钻（≤2 次）定位条款节点；
2. BM25 兜底：导航失败/低置信时词面检索；两路合并统一打分重排，取 top4；
3. 生成：节点原文直接进 prompt；金额/比例逐字校验（不符自动修复一次，仍不符则标注提醒）；
4. 引用：输出「文档｜章节｜小节」路径，可点对点核对到源 txt。

## Agent

- **RAGKnowledgeAgent**（.claude/skills/ask-question/script/agent.py）
- 使用 **model 对象**（需先创建 OpenAIChatModel），**reply() 为 async**

## 返回格式（content JSON）

- status: success / no_knowledge / document_list
- answer: 自然语言答案（末尾带「依据：《文档｜章节｜小节》」）
- proactive_question: 追问（可为空）
- number_check: passed / repaired / failed（数字逐字校验结果）
- sources: [{file, title, path, lines}] —— path+lines 可定位到源文件原文
- retrieved_documents: 命中条款摘要（content ≤200 字 + metadata）
- retrieval: {mode, calls, degraded, nav_hits, bm25_hits} 检索链路埋点

## 知识库维护

- 源文档：data/documents/*.txt（唯一事实源，共 8 篇）
- 树索引：data/tree_index/*.json（构建产物，可 git diff）；源文档变更后重建：

```bash
python .claude/skills/ask-question/script/tree_builder.py
```

- 加载时若源文件 hash 不一致会自动标记 stale 并拒绝使用（不会返回过期答案）

## 调试

```bash
python scripts/rag_query.py "杭州住宿费上限是多少" --top-k 6 --full
```

打印与线上一致的检索结果（得分/章节路径/行号/原文），用于排查「为什么答错」。

## 评测

```bash
python tests/eval_rag_tree.py    # 40 题离线检索评测（无 LLM 最坏情况，CI 门禁）
```

## 回答生成指南

1. 必须严格基于知识原文回答，严禁编造；
2. 金额、比例、天数必须逐字摘自原文（生成后由代码校验）；
3. 知识原文不足以回答时，直接说「知识库中没有相关信息」。