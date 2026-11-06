# 决策层（NeoHorse-Jev-4B）设计与实现

> **版本** v2.0 ｜ **日期** 2026-11-06 ｜ **状态** 已实现（M0–M4），可影子运行
> **代码** `utils/decision_*.py`、`agents/intention_agent.py`（接线）
> **配套** `docs/rag-tree-architecture-dev-plan.md`（另一条线：RAG 树重构，与本层零耦合）

---

## 0. 一页速览

| 问题 | 答案 |
|---|---|
| 用在哪 | 意图路由的**判定环节**：这句是不是请求、属于 13 类意图里的哪类、要不要反问 |
| 不替代什么 | 行程生成、RAG 回答、翻译、query 改写、实体抽取——Jev 是**非生成**模型，这些仍归主模型（GLM-5.2 / MiMo） |
| 怎么调 | `POST {base}/decision`，**不是** `/chat/completions`（走后者直接 400） |
| 有多快 | 端到端中位 **461–500ms**（P90 ≈ 559ms，最坏 904ms）；服务端自报决策 **55ms** |
| 有多准 | 24 条金标准集：`is_request` **83.3%**、能力门控 **91.7%**、意图 top-1 **94.4%** |
| 默认状态 | `ALIGO_DECISION_MODE=off`，不配 key 就完全不走；开启后先跑 `shadow` |
| 挂了会怎样 | 熔断 + 降级到现有 LLM 路径，用户无感；一行环境变量可整体关闭 |

**三步开启**：

```bash
# 1) .env 追加（勿覆盖他人条目）
NEOHOUSE_API_KEY=sk_tr_…
ALIGO_DECISION_MODE=shadow

# 2) 跑一天，看影子日志
python tools/replay_shadow.py

# 3) 达标再切 assist / primary
```

---

## 1. 为什么需要决策层

项目的瓶颈不在"生成"，而在"分类判断"——而这正是 Jev 的定义域。

| 现状 | 位置 | 问题 |
|---|---|---|
| 约 800 行正则做意图路由 | `agents/intention_agent.py:52-274` | 只有 0/1 判定，没有置信度；加一条规则要防着击穿另外三条 |
| 6 份修复文档在给正则打补丁 | `tests/fix_specs/fix_01..06` | fast_route_hijack、keyword_too_broad、multi_intent_collapse、memory_false_trigger… |
| 85 条审计用例、13 类 bug | `tests/logic_audit/cases/*.json` | 现成的金标准回归集，但只能证明"正则没崩" |
| 意图识别走思考模型 | `agents/intention_agent.py`，预算 `SCENARIO_TOKENS["intention"]=4096` | 2–8 秒、每次几千 token，只为输出 13 类枚举 + 几个布尔 |
| 二元判定散落各处 | `_resolve_elliptical`、place-search 类型判定、记忆触发 | 全靠关键词表，无法表达"多大概率" |

**一句话**：项目缺的不是更大的模型，是一个会输出概率、单价很低的判定器。

---

## 2. 实证数据（2026-11-06 实测）

### 2.1 接口

```text
POST https://tokenrhythm.studio/v1/decision
Authorization: Bearer sk_tr_…
{"model":"NeoHorse-Jev-4B","state":"…","questions":{…}}

200 {"model":"NeoHorse-Jev-4B","answers":{…},"input_tokens":390,
     "decision_seconds":0.0554,"probability_source":"pointer_head"}
```

| 项 | 实测 |
|---|---|
| 协议 | 独立端点；`/chat/completions` → 400 `MODEL_PROTOCOL_NOT_SUPPORTED`，`/messages` 同样拒绝 |
| 等价端点 | `/v1/decision`（推荐）与 `/v1/systemone` 都可用 |
| 延迟 | 3 题 490ms；生产用的 9 题 461–531ms 中位，P90 559–609ms，最坏 904ms |
| 服务端耗时 | `decision_seconds` 0.054–0.055 |
| Token | 127（3 题）、约 390（9 题；`expanded_tokens` 181） |
| 权限 | 本 key 已获灰度；**403 = 未获灰度** |
| 限流 | 连续压测会触发 **429**（已用 5 分钟决策缓存缓解） |

### 2.2 准确率三轮演进

| 轮次 | 配置 | 样本 | 结果 |
|---|---|---|---|
| v1 | 7 个能力门控平铺一请求 | 18 条 | 严格命中 **55.6%** |
| v2 | `is_request` 前置门控 + 13 类 `choice` + 6 个门控 | 19 条 | 门控 **68.4%** / 意图 **84.2%** |
| **v3（当前）** | 上面的题面 + **逐门控阈值** + **主意图门控回填** + 缓存 | 24 条金标准集 | `is_request` **83.3%** / 门控 **91.7%** / 意图 **94.4%** |

### 2.3 三条结论（决定了现在的架构）

1. **`choice` 头明显强于独立 `noul` 头**（84% vs 68%）。同一次请求里各题概率独立计算，会自相矛盾（"意图=行程规划"但"want_trip=0.47"）。
   → 主意图用 `choice`；门控只做辅助，并在主意图高置信时**回填**对应门控（见 §3.3）。
2. **阈值必须按门控分别设**。"我想去北京"得到 `want_scenic=0.86`，统一 0.5 阈值会误开景点搜索——正是 KB/PS 类 bug 的镜像。
3. **`state` 的写法影响很大**。加"场景 / 最近对话 / 已知实体"后，`is_request` 判定明显变稳。
   → 决策层内置项目专用 state 模板，不把裸 query 直接丢进去。

> 结论：**"低置信升级 LLM"是架构的一部分，不是补丁**。Jev 处理掉大部分明确请求，其余交给现有 LLM。

---

## 3. 架构

### 3.1 数据流

```text
用户输入
  │
  ├─(1) _resolve_deixis / _resolve_elliptical         现有逻辑，不动
  │
  ├─(2) _fast_match                                   现有正则，不动
  │
  ├─(3) maybe_use_decision(query, history, fast)      ← 唯一接线点
  │       │
  │       ├─ off      → 原样返回（零开销）
  │       ├─ shadow   → 异步旁路，写 jsonl，原样返回
  │       ├─ assist   → 同步复核：仅"高风险命中"才付 500ms，可否决
  │       └─ primary  → assist + 高置信直通（免一次 LLM）
  │
  ├─(4) 命中 → 直接返回 agent_schedule（fast 或 decision）
  │
  └─(5) 未命中 → 现有 LLM 意图识别（4096 token 预算不变）
```

### 3.2 四种模式的行为矩阵

| 模式 | 是否请求模型 | 能否否决正则 | 能否直通 | 额外延迟 | 适用 |
|---|---|---|---|---|---|
| `off` | 否 | 否 | 否 | 0 | 默认、回滚 |
| `shadow` | 是（异步） | 否 | 否 | ≈0（不阻塞） | 上线观察期 |
| `assist` | 是（同步，仅高风险命中） | **是** | 否 | +400–600ms（只在这 4 类） | 稳定期 |
| `primary` | 是（同步，含未命中） | 是 | **是**（限 5 类意图） | 命中 +500ms；直通省 2–8s | 数据校准后 |

- **高风险命中**：`hotel_search / restaurant_search / scenic_search / memory_query` 四类才复核（其余正则足够确定，不值得多付延迟）
- **可直通意图**：`rag_knowledge / preference / expense_tracking / currency_conversion / translation`——它们只吃 query，不需要 `key_entities` / `fast_event`

### 3.3 决策规则

**否决（veto）** —— 只对高风险命中生效，满足任一条即撤销正则结果、回退 LLM：

| # | 条件 | 用意 |
|---|---|---|
| 1 | `intent == chitchat` 且 `p ≥ 0.60` | 明确在闲聊，却命中"找酒店" |
| 2 | `p_is_request < 0.35` 且 `p_intent < 0.60` | 模型觉得不像请求，自己也没把握 |
| 3 | 主意图 ≠ 正则意图，`p_intent ≥ 0.85`，且正则意图概率 ≤ 0.05 | 模型很确信是另一件事 |

> 规则 2 特意要求"低置信"：实测祈使句（"翻译成俄语" 0.09、"记一笔打车费 50 元" 0.35）的 `is_request` 天然偏低，否则会误杀正常请求。

**直通（rescue）** —— 仅 `primary`，需同时满足：正则未命中、意图在可直通集合、`p_intent ≥ 0.90`、无冲突标记。

**门控回填** —— `p_intent ≥ 0.55` 时，把主意图对应的门控置真（冲突仍按**原始**概率记录到 `conflicts`，供回放分析）。

### 3.4 降级链

```text
200            → 用概率
401            → 记 error，本次降级
403            → 进程内永久禁用（灰度未开），不再尝试
429 / 5xx / 超时 → 熔断计数（5 次开、60s 半开）+ 本次降级
422            → 记日志 + 本次降级（不做截断重试，避免雪崩）
解析失败        → 本次降级
```

任何分支都不向用户抛错；主链路行为与接入前一致。

---

## 4. 模块与代码地图

### 4.1 文件清单

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `utils/decision_schema.py` | 13 类意图、6 个能力门控、state 模板、意图→agent 映射 | `build_state()`、`build_questions()`、`intention_from_decision()` |
| `utils/decision_types.py` | 数据结构 | `RouteDecision`、`ShadowRecord` |
| `utils/decision_thresholds.py` | 阈值表 + 热加载（mtime 缓存） | `load_thresholds()`、`gate_threshold()` |
| `utils/decision_engine.py` | HTTP 客户端 + 缓存 + 熔断 + 解析 | `DecisionEngine.from_config()`、`route()`、`route_sync()`、`log()` |
| `utils/decision_router.py` | 与 IntentionAgent 的接线、veto/rescue | `maybe_use_decision()`、`decision_status()` |
| `agents/intention_agent.py` | **唯一**被修改的存量文件 | `reply()` 内新增十余行（含 import 与两处日志） |
| `config.py` | `DECISION_CONFIG` | 与引擎环境变量同源 |
| `server/app.py` | 启动探活 | mode≠off 时打一行结论 |
| `server/routes/health.py` | `decision_layer` 字段 | 运维可见 |

### 4.2 关键接口（实际实现）

```python
class DecisionEngine:
    @classmethod
    def from_config(cls, cfg: dict) -> "DecisionEngine | None": ...   # mode=off / 无 key → None
    @classmethod
    def from_env(cls) -> "DecisionEngine | None": ...                 # 读环境变量
    async def decide(self, state, questions, *, timeout=None) -> dict # 原始响应，失败抛 DecisionUnavailable
    async def route(self, query, history=None, entities=None) -> RouteDecision | None
    def route_sync(self, query, history=None, entities=None) -> RouteDecision | None
    def log(self, record: ShadowRecord) -> None                       # JSONL 落盘
    def status(self) -> dict                                          # health 用

class RouteDecision:
    intent, p_intent, intent_probs, is_request, p_is_request, need_clarify,
    gates, gate_flags, conflicts, latency_ms, input_tokens, decision_seconds, trace_id

async def maybe_use_decision(query, history, fast) -> DecisionHook
# DecisionHook: .fast（替换后的结果，None=走 LLM）、.source（fast|decision|veto|off）、.log_outcome()
```

---

## 5. 接口契约（`POST /v1/decision`）

| 字段 | 说明 |
|---|---|
| `model` | 固定 `NeoHorse-Jev-4B` |
| `state` | 字符串或 JSON，背景/待判断内容 |
| `questions` | 1–16 题；键由调用方定义，回包按同键读取 |
| `choice` | `criteria` = {选项: 描述}，1–255 项 → 返回 `choice` + `probabilities` |
| `noul` | 是/否 → 返回 `noul` = P(true)，阈值自定 |
| `score` | `criteria` = 2–10 档数组（低→高）→ 返回 0 起始的期望等级 |
| 限制 | 请求体 ≤1MiB；带图只能 1 题、≤8MiB（PNG base64 data URL） |
| 错误 | 401 key 无效 / 403 未获灰度 / 413 超限 / 422 参数 / 429 限流 / 502–504 上游 |

**本项目实际发的 9 题**：`is_request`（noul）、`intent`（choice，13 项）、`need_clarify`（noul）、`want_trip / want_hotel / want_restaurant / want_scenic / want_info / want_memory`（noul）。

响应样例（真实回包，节选）：

```json
{"model":"NeoHorse-Jev-4B",
 "answers":{"intent":{"choice":"hotel_search",
                       "probabilities":{"hotel_search":0.91,"itinerary_planning":0.05}},
            "is_request":{"noul":0.97}},
 "input_tokens":390,"decision_seconds":0.055,"probability_source":"pointer_head"}
```

---

## 6. 阈值体系

**默认值**（`utils/decision_thresholds.py`，可被 `data/decision_thresholds.json` 覆盖，热加载）：

| 键 | 默认 | 含义 |
|---|---|---|
| `p_intent` | 0.90 | 直通所需的主意图置信度 |
| `p_intent_floor` | 0.55 | 低于此值不做门控回填 |
| `p_is_request` | 0.40 | 判为"请求"的阈值 |
| `p_gate` / `per_gate` | 0.80 / 0.75–0.85 | 各能力门控阈值（记忆类最严 0.85，搜索类 0.75） |
| `p_clarify` | 0.75 | 反问判定（0.3–0.7 区间一律交 LLM） |
| `veto.p_is_request_below` | 0.35 | 否决规则 2 的前件 |
| `veto.p_chitchat_above` | 0.60 | 否决规则 1 的前件 |
| `veto.min_confident_intent` | 0.60 | 否决规则 2 的"低置信"界限 |
| `timeout_sec` | 8.0 | 单次请求超时 |
| `circuit.*` | 5 次 / 60s | 熔断阈值与恢复时间 |

**调参流程**：改 `data/decision_thresholds.json` → 重跑 `tests/test_decision_eval.py`（门禁 75/60/70）→ 达标再切模式。改阈值不需要改代码、不需要重启。

---

## 7. 配置项

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `NEOHOUSE_API_KEY` | 空 | 平台 key；空则决策层不存在 |
| `NEOHOUSE_BASE_URL` | `https://tokenrhythm.studio/v1` | 统一 base |
| `NEOHOUSE_MODEL` | `NeoHorse-Jev-4B` | 固定 |
| `ALIGO_DECISION_MODE` | `off` | `off / shadow / assist / primary` |
| `ALIGO_DECISION_TIMEOUT` | `8` | 单次超时（秒） |
| `ALIGO_DECISION_CACHE_TTL` | `300` | 同 query 决策缓存（秒），0 = 关闭 |
| `ALIGO_DECISION_SHADOW_DIR` | `data/decision_shadow` | 影子日志目录 |
| `ALIGO_DECISION_THRESHOLDS` | `data/decision_thresholds.json` | 阈值覆盖文件 |
| `ALIGO_DECISION_EVAL` | 空 | 设为 1 才跑联网评测 |

`config.py` 的 `DECISION_CONFIG` 与上表同源，供 `server/app.py` 探活与运维读取。

---

## 8. 运行手册

### 8.1 启用

```bash
# .env（追加，勿覆盖他人条目）
NEOHOUSE_API_KEY=sk_tr_…
NEOHOUSE_BASE_URL=https://tokenrhythm.studio/v1
ALIGO_DECISION_MODE=shadow
```

### 8.2 常用命令

```bash
python tools/probe_neohorse.py                              # 连通性 + 模型清单
python tools/bench_decision.py                              # 24 条金标准集快速基准
python tools/bench_decision.py --verbose                    # 打印每条期望/实得
python tools/replay_shadow.py                               # 影子一致率 / 路径分布 / 冲突数
python tools/replay_shadow.py --date 20261106 --csv r.csv   # 指定日期并导出明细
pytest tests/test_decision_engine.py tests/test_decision_integration.py -q
ALIGO_DECISION_EVAL=1 pytest tests/test_decision_eval.py -q -s   # 联网评测（门禁）
```

### 8.3 排障

| 现象 | 含义 | 处理 |
|---|---|---|
| 400 `MODEL_PROTOCOL_NOT_SUPPORTED` | 调了 `/chat/completions` | 改调 `/decision` |
| 403 | key 未获灰度 | 找平台开通；引擎会进程内永久禁用并降级 |
| 401 | key 无效/过期 | 换 key，重启 |
| 429 | 限流 | 引擎记失败并熔断；查 `ALIGO_DECISION_CACHE_TTL` 是否被关掉 |
| 422 | 题数/长度超限 | 检查 `questions` 数量（≤16）与 `state` 长度 |
| `/api/health` 里 `decision_layer.enabled=false` | mode=off 或无 key，或 403 已禁用 | 看 `last_error` 与 `circuit.state` |
| 影子目录为空 | mode=off、key 缺失，或请求都被缓存命中 | 确认 `ALIGO_DECISION_MODE` 与目录权限 |

---

## 9. 测试与评测

| 层次 | 文件 | 覆盖 | 是否需要网络 |
|---|---|---|---|
| 单测 | `tests/test_decision_engine.py` | 配置解析、响应归一化、冲突、熔断/403、缓存、影子日志、veto/rescue 规则 | 否 |
| 接线 | `tests/test_decision_integration.py` | 真实 `reply()` 四模式行为（assist 否决→LLM、shadow 不改结果、primary 直通、off 无影响） | 否（注入 agentscope stub） |
| 联网评测 | `tests/test_decision_eval.py` | 24 条金标准集，门禁 75/60/70 | 是（`ALIGO_DECISION_EVAL=1`） |

**当前结果**：单测 + 接线 **38 项全绿**；联网评测 `is_request` 83.3%、门控 91.7%、意图 94.4%。

金标准集（`tests/decision_eval/cases.json`）覆盖：关键词过宽 6、记忆误触发 4、多意图 4、差旅劫持 2、地点类型 1、火车票歧义 2、翻译/记账 2、对抗 3。

---

## 10. 与 RAG 树会话的协作

| 文件 | 归属 | 本层做法 |
|---|---|---|
| `.claude/skills/ask-question/**`、`rag_core/**` | 对方 | 全程未触碰 |
| `config.py` / `server/app.py` / `CLAUDE.md` | 对方先改完 | M4 阶段**追加**（不重排） |
| `agents/intention_agent.py` | 本层唯一存量改动 | 只插入调用，不动正则/prompt |
| `tests/`、`data/`、`docs/` | 各自新增 | 文件名/目录不重叠 |

**注意**：当前目录尚未初始化 git（`git status` 报 not a git repository），并行改动没有回滚兜底，建议尽快 `git init` 并提交基线。

---

## 11. 风险与已知限制

| # | 风险 | 对策 |
|---|---|---|
| R1 | 项目域准确率仍不足 100%（金标准集 83–94%） | 低置信一律升级 LLM；不做全量切换 |
| R2 | 灰度权限被收回 / 涨价 | 一行 `ALIGO_DECISION_MODE=off` 回退；契约按"可替换引擎"设计 |
| R3 | 延迟抖动（最坏 904ms） | 8s 超时 + 熔断 + 只在高风险命中时同步等待 |
| R4 | 概率≠校准正确率（官方明示） | 阈值按门控分别设；对外不承诺"90% 准" |
| R5 | 双套判定逻辑维护成本 | 正则退化为 trigger 后逐步删减；影子数据驱动收敛 |

**已知不完美**：

- `is_request` 对祈使句系统性偏低（翻译 0.09、记账 0.35）→ 不把它当直通门槛；
- 多意图里的第三个意图（如 FR-004 的"西湖玩"）门控常低于阈值 → 交 LLM 兜底；
- 本机 `agentscope` 2.0.8 与项目 pin 的 1.0.16 不匹配，真实链路需在正确环境复验；
- 24 条金标准集只能反映"已知坑"，不代表线上分布（需影子数据补足）。

---

## 12. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 11-06 | v1.0 | 方案初稿：接口调研、三轮基准、里程碑拆解 |
| 11-06 | v1.1 | 实现 M0–M3：引擎/接线/影子/阈值；单测与接线测试通过 |
| 11-06 | v1.2 | M4 收口：`DECISION_CONFIG`、启动探活、health 字段、CLAUDE.md 小节 |
| 11-06 | v2.0 | 文档重写：合并"计划"与"实现状态"，统一口径与编号；修正过期描述（19→24 用例、接口签名、模块状态） |

---

## 附录 A · 实测样本

请求（简）：

```json
{"model":"NeoHorse-Jev-4B","state":"【场景】旅行助手\n【用户本轮输入】我住在北京朝阳区",
 "questions":{"is_request":{"type":"noul","instructions":"这一句是在提出查询或请求吗？"},
              "intent":{"type":"choice","instructions":"主要意图？",
                        "criteria":{"chitchat":"闲聊","hotel_search":"找住宿"}}}}
```

回包：`is_request=0.30`、`intent=chitchat(0.75)`、`decision_seconds=0.055` → 判为闲聊，不触发酒店搜索。

## 附录 B · 术语

| 术语 | 含义 |
|---|---|
| choice / noul / score | Jev 的三种决策题型：多选一 / 是-否概率 / 等级期望 |
| 门控（gate） | 某个能力"要不要调用"的布尔判断（由 noul 概率 + 阈值得到） |
| veto | 决策层否决正则的误命中，回退 LLM |
| rescue | 决策层在正则未命中时高置信直通 |
| 影子（shadow） | 只记录判断、不影响返回值的观察模式 |
