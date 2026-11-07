# Aligo 智能旅行助手

## 项目概述

多智能体旅行规划系统，基于 AgentScope 2.0.11 框架 + 小米 MiMo 大模型，采用 Plan-and-Execute 架构。

- CLI 入口：`cli.py`（Rich 终端 UI）
- Web 入口：`server/app.py`（FastAPI） + `web/`（React 19 + Vite）
- 核心编排：`agents/`（IntentionAgent → OrchestrationAgent → Skill 插件）
- 记忆系统：`context/`（短期内存滑动窗口 + 长期 JSON 持久化）
- Skill 插件：`.claude/skills/`（10 个独立插件，懒加载）

## 常用命令

```bash
# CLI 交互
python cli.py

# Web 开发模式
cd server && uvicorn app:app --reload --port 8000   # 后端
cd web && npm run dev                                 # 前端 (localhost:5173)

# Web 生产模式
cd web && npm run build    # 构建前端到 web/dist/
python server/app.py       # FastAPI 同时提供 API 和静态文件

# 测试
pytest                            # 全部测试
pytest tests/test_intention_agent.py  # 单模块
python tests/test_cli_qa.py       # 端到端集成

# 决策层（NeoHorse-Jev-4B）：影子回放 / 金标准集 / 接线测试
python tools/replay_shadow.py                     # 影子一致率、路径分布、冲突数
python tools/bench_decision.py                    # 24 条金标准集（需 NEOHOUSE_API_KEY）
pytest tests/test_decision_engine.py tests/test_decision_integration.py -q

# 知识库（树索引）重建：源文档变更后运行；检索评测 / 单题调试
python scripts/build_rag_index.py
python tests/eval_rag_tree.py
python scripts/rag_query.py "杭州住宿费上限是多少"   # 看这条问题会检索到什么

# 健康检查
python cli.py health
```

## 架构要点

### 意图识别与调度流程

```
用户输入 → IntentionAgent (LLM意图识别, 6大类)
         → OrchestrationAgent (按优先级调度)
         → 同优先级 Skill 并行执行 (asyncio.gather)
         → 结果聚合 → 记忆更新 → 响应
```

### 6 大意图类型

| 意图 | Skill | 说明 |
|------|-------|------|
| itinerary_planning | plan-trip | 行程规划 |
| memory_query | memory-query | 查询历史记忆 |
| preference | preference | 偏好管理（追加/覆盖） |
| rag_knowledge | ask-question | RAG 知识库问答（树索引+推理导航，2026-11） |
| information_query | query-info | 天气/网络搜索 |
| event_collection | event-collection | 行程要素提取 |
| hotel_search | place-search | 酒店/民宿搜索（高德POI） |
| restaurant_search | place-search | 餐厅/美食搜索（高德POI） |
| scenic_search | place-search | 景点/旅游搜索（高德POI） |

### 额外 Skill 插件

| Skill | 说明 |
|-------|------|
| place-search | 地点搜索（酒店/餐厅/景点，高德POI API） |
| expense-tracker | 费用记录与汇总 |
| currency-converter | 汇率查询（frankfurter.app） |
| translation | 多语言翻译（MyMemory API） |
| visa-info | 签证政策查询（树导航版，2026-11） |
| train-ticket | 火车票查询（12306） |

### 记忆系统

- **短期记忆** (`context/short_term_memory.py`)：内存滑动窗口，10 轮对话
- **长期记忆** (`context/long_term_memory.py`)：`data/memory/{user_id}.json`，存储偏好/行程/聊天/费用
- **记忆管理** (`context/memory_manager.py`)：统一门面，LLM 异步总结

### Web 服务

- `server/routes/chat.py`：`POST /api/chat`，SSE 流式响应
- `server/routes/memory.py`：REST API（历史/偏好/费用/插件管理）
- `server/session.py`：LRU 会话缓存（最多 50 个）
- `web/src/api/client.ts`：SSE 客户端 + REST helper
- `web/src/store/chatStore.ts`：Zustand 状态管理

### 决策层（NeoHorse-Jev-4B，2026-11）

- `utils/decision_engine.py`：`POST /v1/decision` 客户端（非 OpenAI 协议），失败即降级；含熔断与 5 分钟决策缓存
- `utils/decision_router.py`：与 `IntentionAgent` 的唯一接线点，四档 `off/shadow/assist/primary`
- `utils/decision_schema.py`：13 类意图 + 6 个能力门控题面；`utils/decision_thresholds.py`：阈值表（`data/decision_thresholds.json` 热覆盖）
- 影子日志 `data/decision_shadow/*.jsonl`；回放报表 `python tools/replay_shadow.py`
- 默认 `ALIGO_DECISION_MODE=off`：不配 `NEOHOUSE_API_KEY` 时完全不走决策层
- 后端可选：`ALIGO_DECISION_BACKEND=custom|jev`（默认 custom=自研 `/v1/decision` 客户端；jev=agentscope `JevClassifierModel` 走 TypeSafe `/v1/systemone`，需 `typesafe-sdk` 与真实 key）
- 运行状态：`GET /api/health` 的 `decision_layer` 字段（mode / 熔断状态 / last_error）
- 方案与实测数据：`docs/decision-layer-dev-plan.md`

## 配置

- `config.py`：LLM / RAG / 决策层 / 稳定性 配置
- `.env`：环境变量（`ALIGO_API_KEY`, `ALIGO_MODEL_NAME`, `ALIGO_BASE_URL`；决策层 `NEOHOUSE_API_KEY`, `ALIGO_DECISION_MODE`）
- `data/plugin_config.json`：插件启用/禁用

## 关键约定

- **AgentScope 1.x 写法禁令**（CI 门禁 `tools/check_as2_gate.py` 强制）：业务代码禁止 `from agentscope.agent import AgentBase`（2.x 已删）、`agentscope.init()`（已删）、`Msg(content=<裸str>)`、`json.loads(x.content)`、`str(content)`、`.content[...]` 切片、`model([...dict...])`——一律走 `utils/as_compat.py`：`mk_msg / msg_text / msg_json / as_messages / chat_text / build_chat_model / setup`
- 所有子 Agent 继承 `agents/base.py::SkillAgentBase`（取代已删除的 AgentBase），`reply()` 为 async，需 await
- Agent 使用 `model=model` 传入已创建的 OpenAIChatModel 实例
- Skill 通过 `LazyAgentRegistry` 动态发现，首次调用时加载
- LLM 输出 JSON 解析有 6 种降级策略（`utils/json_parser.py`）
- 熔断器连续失败 5 次后暂停，60 秒后半开恢复（`utils/circuit_breaker.py`）
- 决策层是**增强项**：`maybe_use_decision()` 的任何异常都必须降级到 LLM/规则，不得影响主链路

## 目录速查

| 路径 | 说明 |
|------|------|
| `agents/base.py` | SkillAgentBase（全项目唯一 Agent 基类） |
| `utils/as_compat.py` | AgentScope 1.x/2.x 适配层（消息文本通道唯一出口） |
| `agents/intention_agent.py` | 意图识别 |
| `agents/orchestration_agent.py` | 协调调度 |
| `agents/lazy_agent_registry.py` | 插件发现与懒加载 |
| `context/` | 记忆系统 |
| `utils/circuit_breaker.py` | 熔断器 |
| `utils/llm_resilience.py` | 重试退避 + 健康检查 |
| `utils/json_parser.py` | 健壮 JSON 解析 |
| `utils/skill_loader.py` | SKILL.md 元数据解析 |
| `server/` | FastAPI 后端 |
| `web/` | React 前端 |
| `tests/` | 测试套件（12 个文件） |
| `.claude/skills/` | 10 个 Skill 插件 |
| `data/memory/` | 用户长期记忆 JSON |
| `data/models/` | （已弃用：树后端无需 embedding，可删除） |
| `rag_core/` | 共享 RAG 核：tree_store / tree_builder / navigator / bm25_fallback / answerer |
| `.claude/skills/ask-question/data/tree_index/` | 差旅知识树索引（tree_builder.py 产物） |
| `.claude/skills/visa-info/data/tree_index/` | 签证知识树索引 |
| `tests/eval_rag_tree.py` | RAG 检索离线评测（40 题，CI 门禁） |
| `docs/rag-tree-architecture-dev-plan.md` | RAG 树架构开发方案 |
| `utils/decision_*.py` | 决策层：schema / types / thresholds / engine / router / jev（TypeSafe 后端适配） |
| `tests/decision_eval/cases.json` | 决策层金标准集（24 条） |
| `data/decision_shadow/` | 决策层影子日志（jsonl，按日滚动） |
| `docs/decision-layer-dev-plan.md` | 决策层设计与实现文档 |
| `docs/decision-shadow-analysis.md` | 影子回放分析与 assist 提升评估（含否决模拟结论） |
| `docs/testing-full-suite.md` | 全量测试「零跳过」复跑指南（服务 / 前端构建 / 音频 mock / 决策 key） |
| `docs/ci-and-hooks.md` | 提交门禁与 CI（pre-commit 安装 / 密钥扫描 / CI 激活步骤） |
| `docs/ci-workflow.yml` | CI 工作流内容（待复制到 .github/workflows/ci.yml 激活） |
| `tools/install_hooks.py` | 安装本地 pre-commit 门禁钩子（每个克隆装一次） |
| `tools/collect_shadow_samples.py` / `tools/simulate_assist_veto.py` | 影子样本采集 / assist 否决离线模拟 |
| `docs/agentscope-2-upgrade-dev-plan.md` | AgentScope 2.0.11 升级与架构重构开发计划（含实测 API 速查与门禁方案） |
| `docs/agentscope-2-delivery.md` | 升级交付说明（范围 / 验收 / 踩坑 / 回滚，README 摘要） |
| `docs/agentscope-2-baseline.md` | 升级基线与双版本验证记录 |
| `experiments/as211_probe*.py` / `impact_audit.py` / `hazard_scan.py` | 升级计划的实证脚本：wheel API 探测 / 冲击面审计 / 静默点扫描 |
