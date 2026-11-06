# RAG 树索引架构 · 方案与运维手册

> 状态：**已实施**（2026-11-06）｜适用范围：ask-question（差旅政策）+ visa-info（签证政策）｜代码：`rag_core/`
> 配套文档：选型调研 [rag-upgrade-research-2026.md](rag-upgrade-research-2026.md)

---

## 0. 快速开始

**日常只需三条命令**（均在项目根目录执行）：

```bash
python scripts/build_rag_index.py     # 改了 data/documents/*.txt 之后重建树索引
python tests/eval_rag_tree.py         # 40 题检索自检（离线，不需要 API Key）
python -m pytest tests/test_tree_builder.py tests/test_navigator.py \
                 tests/test_bm25_fallback.py tests/test_answerer_validation.py tests/test_rag_documents.py -q
```

**当前指标**（40 题评测集，无 LLM 的最坏情况）：

| 指标 | 结果 | 说明 |
|---|---|---|
| Hit@4（生产 top_k） | **0.975** | 标准答案是否出现在交给 LLM 的 4 段原文中 |
| Hit@3 | 0.900 | 同上，取前 3 |
| Hit@1 | 0.550 | 排序精度（宽泛父章节会排前，见 §10） |
| MRR | 0.727 | 同上 |
| 冷启动 | **0s** | 不加载 embedding、不连向量库 |
| 依赖 | **jieba + rank-bm25** | 已无 pymilvus / sentence-transformers |

---

## 1. 为什么换掉向量检索

### 1.1 旧实现的五个问题

| # | 问题 | 后果 |
|---|---|---|
| P1 | 600 字固定切块，把「标题—条款—数字」切散 | 二线标准被答成一线标准 |
| P2 | 单路 dense 向量，政策问答依赖精确词面（500元/晚、30个自然日、增值税发票） | 词面明确的问题反而召回差 |
| P3 | 「二次检索」靠往 query 后拼关键词（具体标准 比例 折扣 金额） | 不稳定，换个问法就失效 |
| P4 | 引用只到文件级（《差旅标准和规定》） | 用户无法核对到条款，答案像编的 |
| P5 | Milvus Lite + bge 冷启动 ~2s、90MB 模型、gRPC 调参 | 启动慢、运维点多 |

### 1.2 目标与达成

| 目标 | 结果 |
|---|---|
| 条款级定位 + 可溯源引用 | ✅ sources 带「文档｜章节｜小节」+ 行号 |
| 金额/比例不允许改写 | ✅ 生成后代码校验，不符自动修复一次 |
| 去掉向量库与 embedding | ✅ 依赖只剩 jieba + rank-bm25 |
| 冷启动 0s | ✅ server 启动不再加载模型 |
| 检索质量不降 | ✅ 离线 Hit@4 = 0.975（旧向量基线 Hit@3 = 0.82 / 28 题） |

---

## 2. 架构

### 2.1 查询链路

```
用户问题（OrchestrationAgent 改写后的 rewritten_query）
   │
   ▼
RAGKnowledgeAgent.retrieve(query)                     ← 两个技能共用同一实现
   ├─ ① 树导航 Navigator
   │     ├─ L1 文档路由：关键词规则 → BM25 文档投票 → （可选）LLM 选文档
   │     └─ L2 节点下钻：标题直匹配 / bigram 打分 / LLM 逐层选（≤2 次调用）
   ├─ ② BM25 词面兜底（全节点索引，jieba 分词 + 标题加权）
   ├─ ③ 合并去重 → 统一打分（导航命中 +0.6 加权）→ 祖先去冗余
   └─ ④ 取 top4 节点原文（含父章节全文）
   ▼
Answerer.generate()  →  数字逐字校验（不符自动修复 1 次）→ 拼接引用
```

### 2.2 索引期 vs 查询期

| 阶段 | 触发 | 做什么 | 依赖 |
|---|---|---|---|
| 索引期 | 手动 / 源文档变更 | `data/documents/*.txt` → 解析标题层级 → 生成 `tree_index/*.json` | 仅正则；`--llm` 时才用 LLM 润色摘要 |
| 查询期 | 每次提问 | 读 JSON 树 + 1-2 次 LLM 导航 + 1 次生成 | LLM（导航/生成） |

### 2.3 三个关键取舍

1. **为什么用「树」而不是「图」**：政策文档天然是「章/节/条款」两级结构，问题几乎都是单跳定位；
   图索引（LightRAG/GraphRAG）需要逐块 LLM 抽实体，索引成本高一个量级，而精确数字问答并不更准。
2. **为什么保留 BM25**：政策问答大量是词面命中（金额、天数、发票类型），词法召回正好补向量/语义的短板；
   同时它是导航失败时的兜底，保证「最差也能答」。
3. **为什么 top_k=4 而不是 3**：评测显示 Hit@3=0.90、Hit@4=0.975；多一段的 token 成本约 350，
   换来 7.5 个百分点的覆盖率，明显划算。

---

## 3. 数据模型

### 3.1 目录

```
.claude/skills/ask-question/data/
├── documents/*.txt          # 唯一事实源（8 篇，人工维护）
└── tree_index/              # 构建产物（可 git diff）
    ├── 01_travel_standards.json
    ├── ...
    └── manifest.json        # 全库卡片：标题 + 摘要 + 关键词 + 源文件 hash
.claude/skills/visa-info/data/  # 同构，4 篇签证文档
```

### 3.2 树文件 Schema

```json
{
  "schema_version": 1,
  "doc_id": "01_travel_standards",
  "source_file": ".../documents/01_travel_standards.txt",
  "source_sha256": "…",              // 与源文件比对，不一致即判 stale
  "title": "阿里商旅差旅标准和规定",
  "summary": "差旅申请流程、交通标准、住宿标准…",   // L1 路由卡片用，≤80 字
  "keywords": ["出差", "住宿", "报销", …],          // 规则路由用
  "tree": [
    {
      "id": "01#h1-3",              // 文档编号#章节序号#小节序号，字符串前缀即父子关系
      "title": "三、住宿标准",
      "summary": "一线城市住宿标准、二线城市住宿标准…",   // 由子节点标题生成
      "line_range": [44, 71],       // 1-based，闭区间，直接切源文件
      "children": [ { "id": "01#h1-3#h2-1", "title": "1. 一线城市住宿标准",
                      "summary": "500元；9折", "line_range": [46, 51], "children": [] } ]
    }
  ]
}
```

要点：

- **正文不进 JSON**：只存结构与摘要，原文按 `line_range` 从 txt 实时切片 —— 只有一份事实，不会两处不一致；
- **id 前缀即父子**：`01#h1-3` 是 `01#h1-3#h2-1` 的祖先，去冗余时按前缀判断；
- **summary 存数字**：启发式摘要优先抽「数字+单位」（如 `500元；9折`），这是导航时最有用的信号。

### 3.3 加载期校验（不通过即拒绝使用）

1. 必填字段齐全、id 全局唯一；
2. `line_range` 单调、不越界；
3. `source_sha256` 与磁盘文件一致 —— 不一致标记 `stale`，该篇不参与检索并写 WARN；
4. 索引导出 `manifest`，供 L1 路由与「有哪些知识库」类问题使用。

---

## 4. 模块说明（`rag_core/`）

| 模块 | 职责 | 关键接口 |
|---|---|---|
| [tree_builder.py](../rag_core/tree_builder.py) | 解析标题 → 建树 → 写 JSON + manifest | `build_all(documents_dir, index_dir, use_llm=False)` |
| [tree_store.py](../rag_core/tree_store.py) | 加载 / 校验 / 切片 / 路径 | `TreeStore.load()`、`node_text()`、`path_of()`、`stats()` |
| [navigator.py](../rag_core/navigator.py) | 文档路由 + 节点下钻 | `Navigator.navigate(query) -> NavResult(hits, llm_calls, degraded)` |
| [bm25_fallback.py](../rag_core/bm25_fallback.py) | 全节点词面检索 / 统一打分 | `search(query, top_k)`、`scores_for(query, keys)` |
| [answerer.py](../rag_core/answerer.py) | 生成 + 数字逐字校验 | `Answerer.generate(query, docs) -> AnswerResult`、`verify_numbers()` |

### 4.1 建树（tree_builder）

- 结构完全取自文档自带层级：`一、`→章节，`1.`/`Q1:`→小节，连续正文归入最近标题；
- 摘要：优先抽「数字+单位」事实，其次首条正文；`--llm` 时由 LLM 改写成≤40 字导航句（失败自动回退启发式）；
- 幂等：源文件 hash 不变可重复执行，结果稳定（除 `generated_at`）。

### 4.2 导航（navigator）

三级策略，成本和精度递增：

| 层级 | 触发条件 | LLM 调用 |
|---|---|---|
| 规则直通 | 标题 4 字/3 字窗口命中问题，或章节 bigram ≥2 | 0 |
| 文档投票 | 规则未命中时，用 BM25 top3 的 doc_id 并入路由 | 0 |
| LLM 下钻 | 以上都无命中 | ≤2（每层 1 次，置信度 <0.6 立即放弃） |

LLM 输出格式固定：`{"selected": ["id"], "expand": true/false, "confidence": 0-1}`，
解析失败/超时/低置信一律返回 `degraded=True`，由上层切 BM25。

### 4.3 生成与校验（answerer）

1. 取节点原文拼上下文（带「文档｜章节｜小节」头）；
2. LLM 生成 JSON：`{"answer", "proactive_question"}`；
3. **数字校验**：正则抽 `数字+单位`（元/天/小时/公里/%/折/…，含区间 8-9折），整串必须在原文中逐字出现；
4. 不通过 → 带「未通过的串」修复一次；仍不通过 → 保留答案但附「（注：部分数字未能与引用条款逐字核对）」并置 `number_check=failed`。

### 4.4 两个技能如何接

```python
# rag_core 只认目录，不认业务
store = TreeStore(index_dir=..., documents_dir=...); store.load()
nav   = Navigator(store, model=self.model)
bm    = BM25Fallback(store)
ans   = Answerer(model=self.model, system="你是签证政策顾问…")
```

---

## 5. 对外契约（改代码时不能碰）

`reply(Msg) -> Msg`，`content` 为 JSON 字符串，字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| status | str | `success` / `no_knowledge` / `document_list` |
| query | str | 实际使用的查询（rewritten_query） |
| answer | str | 答案，末尾带「依据：《文档｜章节｜小节》」 |
| proactive_question | str | 追问，可为空 |
| number_check | str | `passed` / `repaired` / `failed` / `skipped` |
| sources | list | `{file, title, path, lines}`，path+lines 可定位原文 |
| retrieved_documents | list | 命中条款摘要（content ≤200 字） |
| retrieval | dict | 检索埋点：`mode/calls/degraded/nav_hits/bm25_hits` |

agent-question 还额外保留被测试锁定的模块级函数：`list_documents()` / `_LIST_DOC_PATTERN` / `_POLICY_HINT` / `_collect_sources()`。

> 兼容性：`agentscope` 1.x 的 `Msg.content` 是字符串，2.x 是块列表 —— 两个 agent 都做了 `_mk_msg()` 双写兼容，
> 并在 `AgentBase` 缺失时提供最小基类，保证单独运行/测试不依赖框架版本。但生产环境请按 requirements 使用 `agentscope==1.0.16`。

---

## 6. 配置

`config.py` → `RAG_CONFIG`：

| 键 | 默认 | 说明 |
|---|---|---|
| backend | `tree` | 仅作标识；legacy 实现已删除 |
| nav_max_llm_calls | 1 | 单问题导航 LLM 调用上限（实测 2 跳无增益，1 跳足够） |
| nav_use_llm | true | 关掉即纯规则 + BM25（零 LLM 导航延迟） |
| nav_confidence_floor | 0.6 | 低于此置信度直接降级 BM25 |
| nav_timeout_sec | 12 | 单次导航超时（思维链模型单次 4-6s） |
| top_k | 4 | 交给生成模型的节点数 |

环境变量：`ALIGO_RAG_BACKEND` / `ALIGO_RAG_NAV_CALLS` / `ALIGO_RAG_NAV_FLOOR` / `ALIGO_RAG_NAV_TIMEOUT` / `ALIGO_RAG_TOP_K`。

### 6.1 模型对接（实测注意事项）

本项目只需 **OpenAI 兼容的 chat 接口**，不需要 embedding / rerank 模型。填 `.env` 三行即可：

```dotenv
ALIGO_API_KEY=...
ALIGO_MODEL_NAME=glm-5.3-flash
ALIGO_BASE_URL=https://token-api.matvenus.com/v1
```

| 注意点 | 说明 |
|---|---|
| 思维链模型要留足 `max_tokens` | glm-5.3-flash 会先输出 `reasoning_content`；`max_tokens<512` 时可能被思考吃光、content 为空。项目默认 2048，够用 |
| 单次导航 4-6s | 因此 `nav_timeout_sec` 设为 12；超时即降级 BM25，不影响正确性 |
| 温度 | 导航 0.2 / 生成 0.3 更稳，config 里按场景传 |
| 探活 | 启动时 `LLM_PROBE_ON_STARTUP=1` 会打一行通道结论 |

---

## 7. 评测

### 7.1 评测集

`tests/eval_rag_tree.py`，40 题，四层：

| 类别 | 题数 | 例 |
|---|---|---|
| 数值/条款 | 28 | 「杭州住宿费上限是多少」→ 不超过400元/晚 |
| 跨文档/对比 | 4 | 「上海浦东机场离市区多远」 |
| 否定/边界 | 4 | 「出差可以带家属吗」「发票丢了还能报销吗」 |
| 口语化改写 | 4 | 「晚上出行可以坐卧铺吗」 |

判定标准：标准答案串（含单位）是否出现在 top-k 节点原文里 —— 与「LLM 能不能看到答案」等价。

### 7.2 门禁

| 模式 | 门禁 | 实测（2026-11-06，glm-5.3-flash） |
|---|---|---|
| 离线（无 LLM，最坏情况） | Hit@4 ≥ 0.95 | **0.975** ✅（Hit@3 0.900 / MRR 0.744） |
| 在线（带 LLM 导航） | Hit@4 ≥ 0.95 | **0.975** ✅（Hit@1 0.600 / Hit@3 0.875 / MRR 0.754） |
| 在线延迟 | 单题 ≤ 10s | **4.5–7.0s**（平均导航 2.2s，LLM 调用 0.35 次/题） |

> 结论：当前语料上规则 + BM25 已覆盖 38/40，LLM 导航只在规则未命中时兜底，在线指标与离线基本持平；
> 它的价值是覆盖新问法，而不是提升已知问题的排序。追求极低延迟可设环境变量 `ALIGO_RAG_NAV_USE_LLM=0`。

### 7.3 与旧实现对比

| 版本 | Hit@3 | MRR | 冷启动 | 依赖 |
|---|---|---|---|---|
| 旧：bge-small + Milvus + 600 字切块 | 0.82（28 题） | 0.70 | ~2s + 向量库 | pymilvus、sentence-transformers |
| 新：树 + 导航 + BM25（离线） | 0.90（40 题） | 0.744 | 0s | jieba、rank-bm25 |
| 新：树 + LLM 导航（在线） | 0.875（40 题，Hit@4 0.975） | 0.754 | 0s | + LLM 0.35 次/题 |

两套题集不完全相同（新题含更难的跨文档/口语化问法），仅作量级参考。

### 7.4 加题

在 `QUERIES` 里追加 `(问题, 标准答案串, 期望文档编号)` 三元组即可；答案串必须逐字出现在原文里，
否则会误判为未命中。

---

## 8. 运维手册

### 8.1 文档更新流程

```bash
# 1) 改或新增 data/documents/*.txt
# 2) 重建索引
python scripts/build_rag_index.py --ask
# 3) 自检（指标不应下降）
python tests/eval_rag_tree.py
# 4) 抽查一棵树的结构
python -c "import json;d=json.load(open('.claude/skills/ask-question/data/tree_index/manifest.json'));print(d['docs'][0])"
```

### 8.2 调试一条问题为什么答错

```bash
python scripts/rag_query.py "杭州住宿费上限是多少"            # 差旅库
python scripts/rag_query.py "日本签证能停留多久" --skill visa # 签证库
python scripts/rag_query.py "报销需要哪些材料" --top-k 6 --full # 多看几段 + 打印全文
```

输出 = 与线上完全一致的检索路径（无 LLM），能看到每段的得分 / 路径 / 行号：

- `nav_hits=0` → 规则和导航都没命中，看是否该加导航关键词或等 LLM 模式；
- 正确条款排在 top4 之外 → 复制该 case 到 `tests/eval_rag_tree.py` 的 `QUERIES` 固化成回归题；
- 命中了但答错 → 是生成问题，看 `number_check` 与 prompt 约束。

### 8.3 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志 WARN 「源文档已变更，树索引过期」 | 改了 txt 没重建 | 跑 `build_rag_index.py` |
| 答案里出现 `degraded: true` | LLM 导航超时/低置信 | 正常降级到 BM25；频繁出现查导航 prompt 与超时配置 |
| 检索到 0 条 | 索引目录为空 | 确认 `data/tree_index/*.json` 存在且能被 `TreeStore.load()` 读到 |
| `number_check=failed` | 答案数字与原文不符 | 看 `retrieval` 与答案原文，通常是条款没选对；必要时补评测题 |
| 启动报 `cannot import name 'AgentBase'` | 装了 agentscope 2.x | `pip install agentscope==1.0.16` |

### 8.4 回滚

旧向量实现（`agent_legacy.py`、`init_knowledge_base.py`）已在 M3 删除，`ALIGO_RAG_BACKEND=legacy` 不再可用。
如需回退到向量检索，只能从版本库恢复这两个文件并恢复 requirements 中的 pymilvus/sentence-transformers。
**本项目当前不是 git 仓库**，修改前建议先备份 `rag_core/` 与两个技能的 `script/`。

### 8.5 日志

每次检索会打一行 INFO：

```
检索：nav=2 bm25=+3 取 4 | {'mode': 'nav', 'calls': 1, 'degraded': False, 'nav_hits': 2, 'bm25_hits': 3}
```

`nav_hits` 为 0 说明走了纯 BM25（规则和导航都没命中），是优化导航的入口信号。

---

## 9. 测试

| 文件 | 覆盖 | 用例数 |
|---|---|---|
| tests/test_tree_builder.py | 解析结构 / 建树 / 校验 / stale | 3 |
| tests/test_navigator.py | 规则路由 / 规则直通 / 降级 / LLM 下钻 | 5 |
| tests/test_bm25_fallback.py | 精确词面 / 空查询 / 全量索引 | 3 |
| tests/test_answerer_validation.py | 数字校验 / 修复重试 / 通过路径 | 5 |
| tests/test_rag_documents.py | 对外契约 4 项（旧测试，未改动） | 7 |
| tests/eval_rag_tree.py | 40 题检索评测（脚本，不参与 pytest） | — |

**全量基线**（2026-11-06，agentscope 1.0.16）：`149 passed / 7 failed / 7 skipped`；
7 个失败全部是 `openai.OpenAIError: Missing credentials`（本机无 `ALIGO_API_KEY`），与代码无关。

---

## 10. 已知限制与后续

1. **在线评测已完成**（2026-11-06，glm-5.3-flash，见 §7.2/§7.3）；唯一稳定 miss 是「晚上出行可以坐卧铺吗」，
2. **Hit@1 偏低（0.55）**：父章节命中时排序靠前但不够精确；由于上下文取 top4，对答案正确性影响有限，
   若要做「精确到条款」的展示，可给叶子节点加长度惩罚或按 summary 命中度重排。
3. **签证文档路由偏弱**：4 篇文档共享「签证/停留/材料」等词，BM25 文档投票容易串台；
   接 LLM 后由 L1 语义路由解决，离线模式影响可控（答案仍在 top4 内）。
4. **规模上限**：当前设计在几十篇、几百节点量级最优；超过 ~100 篇时按 PageIndex File System 思路
   增加「文件级树」先路由，再进章节树。
5. **`data/models/` 已空置**：树后端不需要 embedding，可删除目录。

---

## 附录 A：文件清单

| 类型 | 路径 |
|---|---|
| 新增（共享包） | `rag_core/{__init__,tree_store,tree_builder,navigator,bm25_fallback,answerer}.py` |
| 新增（入口） | `scripts/build_rag_index.py`、`tests/eval_rag_tree.py` |
| 新增（测试） | `tests/test_tree_builder.py`、`test_navigator.py`、`test_bm25_fallback.py`、`test_answerer_validation.py` |
| 新增（数据） | `.claude/skills/ask-question/data/tree_index/*.json`、`.claude/skills/visa-info/data/tree_index/*.json` |
| 修改 | `.claude/skills/ask-question/script/agent.py`（重写）、`.claude/skills/visa-info/script/agent.py`（迁移）、`config.py`、`server/app.py`、`requirements.txt`、`README.md`、`CLAUDE.md`、两个 `SKILL.md` |
| 删除 | `init_knowledge_base.py`、`agent_legacy.py` |

## 附录 B：里程碑

| 阶段 | 状态 | 内容 |
|---|---|---|
| M0 建树 | ✅ | tree_builder + tree_store + manifest（8 篇 / 76 章节 / 394 节点） |
| M1 检索 | ✅ | navigator + bm25_fallback + answerer |
| M2 切换 | ✅ | agent.py 重写、配置/文档同步、契约保持 |
| M3 清理 | ✅ | 删旧实现与依赖；server 预加载移除 |
| 共享化 | ✅ | 5 模块上移 `rag_core/`，visa-info 迁移（4 篇 / 110 节点） |
| 待办 | ⏳ | 有 Key 后复核 LLM 导航指标 |