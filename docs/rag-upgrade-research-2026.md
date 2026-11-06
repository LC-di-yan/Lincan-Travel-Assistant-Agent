# GitHub 上更新、更高效的 RAG 技术（调研速览 · 2026-11）

> **落地状态**：本报告第六节的选型（PageIndex 式树索引）已于 2026-11-06 实施，
> 模块在 `rag_core/`，方案与运维见 [rag-tree-architecture-dev-plan.md](rag-tree-architecture-dev-plan.md)。文中渐进路线（§四、五）未采用，仅作过程记录。

> 一句话结论：本项目现在是「单路向量召回 + 固定 600 字切块 + top3 + 无重排」，大致落后主流方案两代。
> **架构决策（2026-11-06 更新，见文末第六节）：不走渐进加固，直接替换检索底座 —— 改为 PageIndex 式「文档树索引 + LLM 推理导航」，向量库 / 切块 / embedding 全部下掉，BM25 降为兜底工具。**

---

## 一、GitHub 上当前的主流新方案（按 star，2026-11 数据）

| 仓库 | Star | 核心思路 | 与本项目的关系 |
|---|---|---|---|
| [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | 93.6k | 从 RAG 引擎进化为 "agent-native 上下文数据库" | 重平台，不建议引入，但它的 chunk/检索默认策略可抄 |
| [volcengine/OpenViking](https://github.com/volcengine/OpenViking) | 41.6k | 把 Agent 记忆、知识 RAG、Skill 统一成自演化上下文库 | 新范式风向标（记忆+RAG 融合） |
| [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) | 40.5k | 轻量图 RAG（EMNLP 2025），实体图 + 双层检索，比 GraphRAG 快很多 | 文档规模大、需多跳时才值得 |
| [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex) | 40.1k | **无向量**：给文档建层级树索引，让 LLM 像人翻目录一样推理定位 | 对"制度/条款类长文档"很对症，值得试点 |
| [microsoft/graphrag](https://github.com/microsoft/graphrag) | 36.6k | 社区摘要式图 RAG | 索引成本高，8 篇文档属于杀鸡用牛刀 |
| [Tencent/WeKnora](https://github.com/Tencent/WeKnora) | 36.6k | 文档→可查询 RAG + 推理 Agent + 自维护 Wiki | 参考其"文档即知识库"的产品形态 |
| [NirDiamant/RAG_Techniques](https://github.com/NirDiamant/RAG_Techniques) | 30.2k | 30+ 种 RAG 技巧的可运行 notebook 合集 | **最佳抄作业仓库**，按需取用 |
| [HKUDS/RAG-Anything](https://github.com/HKUDS/RAG-Anything) | 24.4k | 多模态一站式 RAG（PDF/表格/公式） | 文档里出现 PDF/图片时再看 |
| [FlagOpen/FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) | 12.3k | BGE 全家桶：embedding / reranker / 稀疏 | 本项目 embedding 就出自这里，升级也走这里 |
| [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) | 4.1k | 海马体式记忆索引 + 个性化 PageRank 多跳 | 研究向，工程收益有限 |
| [RUC-NLPIR/FlashRAG](https://github.com/RUC-NLPIR/FlashRAG) | 3.6k | RAG 研究工具箱（含大量检索/重排消融） | 做评测时的参考实现 |
| [AnswerDotAI/rerankers](https://github.com/AnswerDotAI/rerankers) | 1.6k | 统一各家的 rerank / cross-encoder 调用接口 | 想省事就用它接重排 |
| [Raudaschl/rag-fusion](https://github.com/Raudaschl/rag-fusion) | 960 | 多查询生成 + RRF 融合 | 查询改写 + 融合的最小实现 |
| [jina-ai/late-chunking](https://github.com/jina-ai/late-chunking) | 542 | 先编码整篇、再按块池化（块保留全局语境） | 进阶切块方案 |

---

## 二、真正值得抄的五类技术

1. **混合检索（Hybrid + RRF）**：BM25（jieba 分词）+ 向量召回，用 Reciprocal Rank Fusion 合并。
   制度类问题大量依赖精确词面（"500 元/晚""30 个自然日""增值税发票"），纯向量恰恰弱在这里。
2. **交叉编码器重排（Rerank）**：先粗召回 top 20，再用 `bge-reranker-v2-m3` 精排取 top 3-5。
   通常是最省事的一档质量提升，代价只是一次小模型前向。
3. **结构化 / 上下文切块**：按"文档标题｜章节｜小节"切，块文本自带标题路径；检索命中小块、喂给 LLM 时扩展成整节（small-to-big）。
   现在的 600 字硬切会把条款和它的标题切散。
4. **Contextual Retrieval（Anthropic 提出）**：入库时让 LLM 给每个块补一句"这段在讲什么"，再嵌入，显著降低"块脱离上下文"的误召回。只花一次索引成本。
5. **查询侧改造**：multi-query + RRF、HyDE、以及 **bge 官方 query 指令前缀**（本项目目前完全没用）。

## 三、两条"更新"的路线（先了解，别急着上）

- **PageIndex（无向量、推理式检索）**：不建向量库，把文档变成带页码的层级树，查询时让 LLM 逐层读目录定位。
  优点是可溯源、对长条款文档准；缺点是每次查询要多次 LLM 调用（延迟/成本换准确率）。适合做"制度全文问答"的第二通道。
- **LightRAG / HippoRAG / GraphRAG（图索引）**：把实体关系建成图做多跳。当前 8 篇文档、问题以单跳条款为主，**收益不匹配成本**，可先不做。

## 四、对本项目的具体差距（可直接改的地方）

| 位置 | 现状 | 建议 |
|---|---|---|
| `agent.py: search_knowledge` | 单路 dense、top_k=3、无重排 | 加 BM25 通道 + RRF 融合，粗召回 20 条再精排 |
| `agent.py: reply` 二次检索 | 往 query 后面拼"具体标准 比例 折扣 金额"的关键词 hack | 换成 multi-query + RRF，或直接靠 hybrid 解决 |
| `init_knowledge_base.py: split_text` | 600 字段落累加、无标题上下文 | 改结构化切块，块首拼"文档｜章节｜小节"路径 |
| query 编码 | 裸 query 直接编码 | 加 bge 指令前缀 `为这个句子生成表示以用于检索相关文章：` |
| 评测 | 无 | 保留一份 20-30 条「问题→标准答案串」的小评测集，改一次量一次 |

**改动成本**：P0（指令前缀 + 结构化切块 + BM25/jieba + RRF）不需要任何新依赖（rank-bm25、jieba 本机已装），约 200 行；
P1（`bge-reranker-v2-m3` 重排）需要下载约 2GB 模型，sentence-transformers 的 CrossEncoder 直接可加载。

## 五、顺带跑过的一次离线对比（仅作参考，不构成严谨结论）

用现有 8 篇文档 + 28 条带标准答案串的问题做了一次离线检索对比（未改主程序）：

| 配置 | Hit@3 | MRR |
|---|---|---|
| 现状（dense, 600 字切块） | 0.82 | 0.70 |
| + bge 指令前缀 | 0.93 | 0.74 |
| BM25 only | 0.89 | 0.73 |
| **dense + BM25 + RRF** | **1.00** | 0.77 |
| 结构化切块 + RRF | 1.00 | **0.85** |

趋势与上面的判断一致：**词面召回补上了向量的短板，结构化切块进一步抬高了排序质量**。
脚本在 `experiments/rag_lab/rag_lab.py`，可随时复跑或丢弃。

---

## 六、架构决策更新：换成 PageIndex 式「树索引 + 推理导航」

结论：检索底座从「向量库 + 切块 + 相似度 top_k」换成「文档层级树 + LLM 逐层推理定位」（vectorless reasoning RAG，
代表实现 [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex) 40.1k）；BM25 仅保留为导航失败时的兜底工具。

### 6.1 候选架构对比

| 架构 | 代表 | 检索机制 | 对本项目的判断 |
|---|---|---|---|
| **树索引 + 推理导航** | PageIndex 40.1k | 文档→层级树，LLM 顺目录推理定位节点 | ✅ 最贴合：条款完整、可溯源到章节、无切块损失；索引约 $0.001/页，查询 1-2 次 LLM 调用 |
| 图 RAG | LightRAG 40.5k / GraphRAG 36.6k | 实体关系图 + 局部/全局检索 | ⚠️ 多跳与全局总结强，但需对 400+ 块逐块 LLM 抽取实体，政策文本噪声大，精确数字并不更准 |
| Agentic 检索循环 | RAGFlow 93.6k / WeKnora 36.6k | 规划→检索→反思→再检索 | ✅ 适合当外循环叠加，本身不是索引形态；与现有 OrchestrationAgent 同构 |
| 图谱记忆 | HippoRAG 4.1k / HyperGraphRAG | PPR / 超图推理 | ❌ 研究向，工程收益不匹配 |
| 平台整体替换 | RAGFlow / WeKnora | 全家桶 | ❌ 等于重写编排层，收益只是默认参数更好 |

### 6.2 选型理由

1. **语料形态命中**：PageIndex 自述最佳场景是财报、法律、监管文件、技术手册——正是本项目的制度/条款文档；它的弱项（扫描件、图片）本项目没有。
2. **痛点一一对应**：600 字切块切断条款 → 节点=完整小节；相似度选错条款 → LLM 读标题推理定位；引用只能到文件级 → 引用输出「文档｜章节｜小节」路径。
3. **工程减法**：删掉 Milvus Lite、bge 模型加载（冷启约 2s / 90MB）、切块脚本约 1000 行；索引产物是 8 个可 git diff 的 JSON 树文件。
4. **规模化路径明确**：文档变多用 PageIndex File System 的文件级树先路由再下钻；真出现跨文档多跳统计，再把 LightRAG 当第二工具挂进来。

### 6.3 目标流水线

```
用户问题
 ├─ L1 文档路由：doc 级目录 + 摘要（8 篇，常驻内存）→ 选定 1-2 篇
 ├─ L2 树内导航：LLM 读「标题 + 一行摘要 + 节点 id」，≤2 步定位到条款节点
 ├─ 兜底：jieba + BM25 词面检索（导航超时/低置信启用，与主路结果取并集）
 └─ 生成：节点原文直接入 prompt；引用输出「文档｜章节｜小节」
```

### 6.4 迁移步骤（可回滚）

1. build_doc_tree.py：用现有 GLM 通道对 8 篇文档生成树（标题 / 一行摘要 / 原文行号），产物存 tree_index/*.json；
2. agent.py 检索层重写为 navigate(query) -> node 列表，保留 reply() 的 prompt、缓存、引用格式不变；
3. 验收：用 28 条带标准答案串的查询集，Hit@3 目标 1.0、金额/比例逐字一致率 100%、P95 延迟增量 < 2s；
4. 旧实现留在 agent_legacy.py，配置开关切换，跑一周稳定后再删。

### 6.5 风险与对策

| 风险 | 对策 |
|---|---|
| LLM 导航选错节点 | 低置信/超时 → BM25 兜底，两路并集交给生成模型 |
| 每次查询多 1-2 次 LLM 往返 | 树摘要常驻内存；只做导航用 fast 模型；导航结果按关键词缓存（复用现有 _RAG_CACHE） |
| 生成阶段改写数字 | 保留现有约束，追加「金额/比例必须逐字摘录，禁止改写」 |
| 跨文档对比/统计类问题 | 树导航一次可取多节点，本就擅长；若出现全局统计再挂 LightRAG 作为第二工具 |
| PDF/扫描件入库 | 届时先解决解析（opendataloader-pdf / RAG-Anything），或直接用 PageIndex Cloud（block 级引用 + OCR） |

### 6.6 一句话备选

如果坚决不接受查询期的额外 LLM 调用，那就选 LightRAG（离线建图、在线纯检索）；
但在这个 8 篇制度文档的规模上，它的精确数字问答质量不会比树导航更好，索引和维护成本却高一个量级。

> 落地实施：[rag-tree-architecture-dev-plan.md](rag-tree-architecture-dev-plan.md)（模块设计、数据 Schema、四阶段排期、验收门禁、风险登记册）。
