# AgentScope 2.0.11 升级与架构重构开发计划

> 状态：**P0–P6a、P8 已完成并验收**（2026-11-06，2.0.11 全量 175 passed / 0 failed）｜P5 停在做加法式桥接（按用户决定）｜P6b/P7 判定不适用或阻塞（见 §11） | 版本基线：agentscope==1.0.16 → **2.0.11（已上线主环境）** | 环境：Python 3.12.8
>
> 一句话结论：**这不是换版本号，是断裂式重设计下的架构重构。** 官方定性 2.0 为 breaking change；本项目对框架的依赖
> 表面很轻（只用 4 个入口），语义却很重（把 Msg.content 当成 JSON 字符串信箱）。真正危险的不是会报错的删除项，
> 而是**不会报错的语义漂移**：实测有 39 处 json.loads(.content)、14 处 str(content)、3 处对 content 做切片/求长度，
> 这些点在 2.0.11 下会静默改变 prompt 内容，测试全绿但线上答非所问。

---

## 0. 本计划的证据来源（全部可复现）

所有 API 结论都不是转述 release notes，而是直接解析 `agentscope-2.0.11-py3-none-any.whl` 源码（AST）得到的。
探测脚本已入库，评审时可重跑验证：

| 脚本 | 关键结论 |
|---|---|
| `experiments/inspect_as211.py` | 2.x 共 26 个子包；`agent/__init__.py` 只导出 `Agent`，**没有 `AgentBase`**；`Requires-Python: >=3.11`；硬依赖 `mcp>=2.0.0` |
| `experiments/as211_probe.py` | 全 wheel 搜索模块级 `def init(` = **0 命中**，即 `agentscope.init` 已删除；`EventType` 全成员；`tool` 导出清单 |
| `experiments/as211_probe2.py` | `OpenAIChatModel.__init__(credential, model, parameters, stream, max_retries, retry_delay, context_size, formatter, client_kwargs, extra_body)`；`middleware`/`classifier`/`rag`/`pipeline`/`permission`/`workspace`/`app` 全量导出 |
| `experiments/as211_probe3.py` | `Msg(BaseModel)` 的 `content: list[ContentBlock]`；`UserMsg/AssistantMsg/SystemMsg` 是**工厂函数**且接受 str（内部 `_to_blocks`）；角色块校验规则；formatter 命名 |
| `experiments/as211_probe5.py` | `Toolkit(tools, skills_or_loaders, mcps, tool_groups, ...)`；`FunctionTool(func, name, description, input_schema, is_concurrency_safe, is_read_only, ...)`；`LocalSkillLoader(directory, scan_subdir)` 原生读 SKILL.md（wheel 内 13 处 SKILL.md 字面量） |
| `experiments/as211_probe6.py` | `JevClassifierModel(credential, model, parameters, timeout, max_retries, retry_delay)`；`ModelRouterMiddleware(classifier_model, candidates, instructions)`；`PermissionMode` 枚举；`AgentState` 字段；`GoalPipeline/TeamPipeline` 签名 |
| `experiments/as211_probe7.py` | `ChatModelBase.__call__(messages: list[Msg], tools, tool_choice, **kwargs)`，且 `**kwargs` 透传到 `_call_api(**generate_kwargs)` → **按调用传 max_tokens 在 2.x 依然有效** |
| `experiments/verify_bits.py` | 全项目 `OpenAIChatModel(` 构造点 = **14**；`parameters` 类型为嵌套类 `OpenAIChatModel.Parameters` |
| `experiments/logger_sig.py` | `setup_logger(level: str, filepath: str | None = None)` 是 `agentscope.init(logging_level=...)` 的替代品 |
| `experiments/impact_audit.py` / `experiments/hazard_scan.py` | §2 冲击面计数与 §1.2 静默点清单 |

---

## 1. 断裂式差异清单

### 1.1 删除/改名（启动即失败 —— 这类反而是好消息）

| 1.x 用法 | 项目内规模 | 2.0.11 现实 | 后果 |
|---|---|---|---|
| `agentscope.init(project=, name=, logging_level=)` | 1 处定义 `config_agentscope.py:21`，18 处引用 | **已删除**。顶层 `__all__ = [logger, setup_logger, set_id_factory, set_timestamp_factory, __version__]`；`init()` 的 `project/name`（Studio 埋点语义）在 2.x 无任何对应 | 启动即 AttributeError |
| `from agentscope.agent import AgentBase` | **47 处引用**，15 处 `class Xxx(AgentBase)`（13 个 Skill + IntentionAgent + OrchestrationAgent） | `agent` 包只导出 `Agent, A2AAgent, RealtimeAgent, TurnAggregator, TurnMetrics, ContextConfig, InjectionConfig, ModelConfig, ReActConfig` | ImportError，全部自定义 Agent 基类消失 |
| `OpenAIChatModel(model_name=, api_key=, generate_kwargs=)` | **14 处构造**（`utils/llm_failover.py` 2、`utils/llm_resilience.py` 1、`rag_core/tree_builder.py` 1、`plan_trip_execution.py` 1、tests 9） | 参数改为 `credential=`（`OpenAICredential(api_key, organization, base_url)`）+ `model=` + `parameters=OpenAIChatModel.Parameters(...)`；`formatter`/`client_kwargs`/`extra_body` 仍在 | TypeError，模型层全灭 |
| `await model([{role, content}])` 传 dict 列表 | **18 处调用点** | `__call__(messages: list[Msg], ...)` 要求 Msg 对象列表 | formatter/取块阶段报错或静默取空 |

### 1.2 语义漂移（不报错 —— 本次升级的真正风险）

2.0.11 里 `Msg` 变成 Pydantic 模型，content 是**块列表**：

```python
class Msg(BaseModel):
    name: str
    content: list[ContentBlock]        # 不再是 str
    role: Literal["user", "assistant", "system"]
    id: str; metadata: dict; created_at: str; usage: Usage | None
    finished_at; finished_reason; structured_output; error
    # 方法：get_text_content(sep) / get_content_blocks(type) / has_content_blocks(type)

def UserMsg(name, content: str | list[TextBlock | DataBlock], ...)     # 工厂函数，str 自动 _to_blocks
def AssistantMsg(name, content: str | list[ContentBlock], ...)
def SystemMsg(name, content: str | list[TextBlock], ...)
# 角色校验：user 只允许 text/data 块；system 只允许 text 块（违反则 ValueError）
```

| 项目现有写法 | 实测处数 | 2.0.11 行为 | 严重度 |
|---|---|---|---|
| `Msg(name=..., content=json.dumps(...), role="assistant")` | **78 处 `Msg(`** | 基类 `Msg` 传裸 str 触发 Pydantic 校验错误（str 被当 Sequence 逐字符校验块） | 高（会报错） |
| `json.loads(msg.content)` | **39 处** | content 是 list → TypeError；若外层有 try/except 则**静默走降级路径**，输出质量悄悄下滑 | **极高（静默）** |
| `user_query = str(content)` | **14 处**（几乎每个 Skill 取用户输入的入口） | 得到块对象的 repr 文本，原样塞进 prompt，**不报错** | **极高（静默）** |
| `msg.content[:500]`、`len(msg.content)` | **3 处**：`agents/intention_agent.py:1001, 1007, 1008` | 切片变成切块、len 变成块数 → 多轮记忆上下文被无声截断成 1 条，意图识别准确率下降且无异常 | **极高（静默）** |
| `Msg(name=..., content={})` 空 dict | 2 处（`event-collection`、`plan-trip`） | 非法，校验异常 | 高 |
| 把记忆摘要当 user/assistant 消息传 | 多处 | 若混入非 text/data 块，user 角色校验抛 ValueError | 中 |

> 判定：约 90% 的升级工作量集中在**消息文本通道**与**模型调用入参**两件事上；
> 而 §1.2 的 56 个静默点必须在同一批改动里一次收干净，否则必然出现「测试绿、线上错」的中间态。

---

## 2. 冲击面量化（实测）

```
受影响 .py 文件（含 skills / tests / tools）：41
  import 语句                     69
  AgentBase 引用                  47
  Msg( 构造                       78
  .content 访问                   80
  模型调用点（await model(...)）    18（含 failover/resilience 内部）
  OpenAIChatModel 构造点           14
  agentscope.init 引用            18
  agentscope formatter 使用        0（3 处命中全是 logging.Formatter）
测试基线：pytest --collect-only -q → 164 tests collected
```

Top 冲击文件：

| 文件 | import | AgentBase | Msg( | .content | 模型调用 |
|---|---|---|---|---|---|
| `agents/intention_agent.py` | 2 | 2 | 4 | 10 | 1 |
| `agents/orchestration_agent.py` | 2 | 4 | 5 | 6 | 0 |
| `tests/test_decision_integration.py` | 2 | 6 | 1 | 5 | 0 |
| `.claude/skills/ask-question/script/agent.py` | 2 | 4 | 3 | 2 | 0 |
| `.claude/skills/query-info/script/agent.py` | 2 | 2 | 5 | 2 | 1 |
| `cli.py` | 2 | 0 | 5 | 2 | 0（含 1 处 init） |
| `server/routes/chat.py` | 1 | 0 | 7 | 0 | 0 |
| 其余 9 个 Skill + 8 个测试 | — | — | 各 1–4 | 各 1–3 | 各 0–2 |

### 关键判断（决定重构方向）

项目**完全没有**使用 AgentScope 的编排能力：无 MsgHub、无 pipeline、无 formatter、无 RAG、无 service；
`IntentionAgent → OrchestrationAgent → asyncio.gather` 全是自研。`AgentBase` 在两个核心类里也只是空壳
（`super().__init__()` 无任何实质作用）。

因此方向不是「把自研编排换成框架编排」，而是：
**把框架降级为「模型网关 + 消息协议 + 工具运行时」，把编排与业务能力收归自己，再按点摘取 2.x 红利。**

---

## 3. 目标架构

### 3.1 分层与依赖方向（重构后）

```
接入层  server/routes/*（SSE 事件协议）、cli.py、web/   ← 只做「事件 → 前端帧」翻译
        │  禁止触碰 Msg.content 原始结构
编排层  agents/orchestration_agent.py（保留自研优先级调度）
        agents/intention_agent.py（改用 structured output，不再手解 JSON）
        [可选] agentscope.pipeline.GoalPipeline / TeamPipeline、agentscope.sop.SOPEngine
能力层  10 个 Skill：纯业务函数（handlers.py）+ FunctionTool 注册 + SKILL.md（LocalSkillLoader）
模型层  utils/as_compat.build_chat_model() → OpenAICredential + OpenAIChatModel(parameters=...)
        utils/llm_failover.py（多通道粘性，包住 Msg-aware 边界）
        [决策层] agentscope.classifier.JevClassifierModel + ModelRouterMiddleware
协议层  utils/as_compat.py：mk_msg / msg_text / msg_json / as_messages / chat_text
        ← 全项目唯一允许接触 content 块结构的模块
```

**四条硬约束，写进 CI 门禁（不是口头约定）：**

1. 业务代码禁止 `from agentscope.agent import AgentBase`（2.x 已不存在）。
2. 业务代码禁止 `Msg(content=<裸str>)`，一律 `as_compat.mk_msg` 或 `AssistantMsg/UserMsg/SystemMsg`。
3. 业务代码禁止 `json.loads(x.content)` / `str(x.content)`，一律 `msg_json` / `msg_text`。
4. 模型调用禁止传 `list[dict]`，一律 `as_messages(...)` 产出 `list[Msg]`。

### 3.2 模块处置矩阵（自研 vs 原生）

| 自研模块 | 处置 | 理由（基于实测 API） |
|---|---|---|
| `utils/decision_engine.py`（自研 Jev 非 OpenAI 协议客户端） | **替换**为 `classifier.JevClassifierModel(credential, model, parameters, timeout, max_retries, retry_delay)` | 2.0.9 起官方内置 Jev 分类器，私有协议客户端可整体退役；`decision_schema.py` 的 13 类意图 + 6 个门控题面直接映射 `ChoiceQuestion`/`BinaryQuestion`/`ScoreQuestion` |
| `utils/decision_router.py`（off/shadow/assist/primary 四档） | **保留壳，换内核**：内部委托 `ModelRouterMiddleware(classifier_model, candidates, instructions)` | 四档灰度、「异常必降级」、影子日志是项目稳定性资产；原生中间件不提供影子回放，接线点必须留 |
| `utils/circuit_breaker.py` | **保留** | 原生只有 `max_retries/retry_delay`（单次调用内）与 `ModelConfig(max_retries, fallback_model)`；跨请求「连续 5 次熔断 + 60s 半开」是业务级保护，2.x 无对应 |
| `utils/llm_failover.py`（多通道粘性） | **保留 + 适配**为 Msg-aware | entitlement/欠费级切通道是运维现实；模型级兜底交给 `ModelConfig.fallback_model`，两层职责分离 |
| `utils/json_parser.py`（6 级降级） | **降为兜底分支** | `reply(inputs, structured_schema=...)`（2.0.5 起）+ `Msg.structured_output` 原生支持，不必再从 markdown 抠 JSON；MiMo 若拒绝 `tool_choice` 仍走我们的降级链 |
| `context/short_term_memory.py`（10 轮滑窗） | **保留并补 `ContextConfig`** | 滑窗是「轮数」语义；`ContextConfig(trigger_ratio, reserve_ratio, tool_result_limit, compression_prompt, summary_template, compression_tool_enabled...)` 是「token + 摘要」语义：滑窗裁剪 + 压缩摘要，互补而非替换 |
| `context/long_term_memory.py`（JSON/PG 持久化） | **保留**，契约不动 | schema 已对外（`/api/memory`、`data/memory/*.json`）；`Mem0Middleware`/`ReMeMiddleware`/`AgenticMemoryMiddleware` 作**增量旁路**实验，本期不迁移数据 |
| `rag_core/`（树索引 + LLM 推理导航 + BM25 兜底） | **保留为差异化资产**，加 `RAGMiddleware(knowledge_bases, parameters, rerank_model)` 适配层 | 树导航有 40 题基线，是强项；原生 RAG 强在向量库与解析器（Word/Excel/PPT/PDF、Milvus/Mongo/ES/Qdrant），弱在推理导航。用 `KnowledgeBase`/`VectorStoreBase` 做桥，不推翻 |
| `.claude/skills/` + `utils/skill_loader.py` + `LazyAgentRegistry` | **迁移到原生** `Toolkit(tools=[...], skills_or_loaders=[LocalSkillLoader(skills_root, scan_subdir=True)])` | 官方 SKILL.md 机制与我们的插件契约同源；`data/plugin_config.json` 启停改为 `ToolGroup` 过滤，保留热加载 |
| 13 个 Skill 的 `class Xxx(AgentBase)` | 改为项目自有 `agents/base.py::SkillAgentBase` | ask-question 里已写过这个 shim（`except ImportError` 兜底），提升为全项目唯一定义，删重复 shim |
| `server/app.py`（FastAPI + 自有 React） | **不替换**为 `agentscope.app.create_app` | 原生 agent-service 极完整（routers: agent/chat/session/skill/knowledge_base/sop/channel/mcp/hub，storage: redis/sql/s3，message_bus，多租户），但会连带替换 `server/routes/*`、`web/src/api/client.ts`、会话 LRU 与 SSE 契约；列为本期后独立评估项 |
| `web/`（React 19） | **不改事件契约**，仅在 P7 加映射 | 前端已有 thinking 流、卡片、SSE 分帧；2.x `EventType` 更细，采用「映射降级 + 只加不改」 |
| 权限与沙箱 | 引入 `PermissionEngine/Rule/Mode` + `FunctionTool(is_read_only=...)`；**不**引入 Docker/K8s workspace | 对 expense-tracker 写入、train-ticket/place-search 外部调用做门控即可；Windows 开发机与容器沙箱不匹配 |
| `agentscope.tui` / `realtime` / `asr` / `channels` / `webui` | **不引入** | 与现有 CLI/Web/语音路线重复，收益不明确 |

### 3.3 升级收益与项目痛点对照

| 已知痛点 | 2.0.11 的解 |
|---|---|
| LLM 输出 JSON 解析失败率高（6 级降级 + 补丁） | `reply(structured_schema=...)` + `Msg.structured_output` |
| MiMo 偶发只返回 thinking 块（`llm_response.py` 为此写特判） | 块类型显式化 + `get_text_content()` + `get_content_blocks(...)` |
| 决策层自建影子/熔断/缓存/私有协议 | `JevClassifierModel` + `ModelRouterMiddleware` + `TracingMiddleware`（OTel） |
| 副作用操作无权限门控 | `PermissionMode` + `REQUIRE_USER_CONFIRM` 事件 + `AskUser`（多选，正好替换自研 `proactive_question` 单串协议） |
| 长行程规划易超上下文 | `Agent.compress_context()` + `ContextConfig` + `workspace.Offloader` 落盘 |
| 同优先级并行靠手写 asyncio.gather | `FunctionTool(is_concurrency_safe=...)` 交给 Agent 批量编排 |
| 看不到 token 成本 | `ChatUsage`（含 `cache_input_tokens`）+ `Msg.usage` + `ReplyBudgetControlMiddleware(token_budget, input_token_weight, output_token_weight, hint_message)` |
| 记忆/费用写入无审计位 | 中间件钩子 `on_reply / on_reasoning / on_acting / on_check_permission / on_model_call / on_compress_context / on_system_prompt` |

---

## 4. 分阶段实施计划

> 排期原则：**先让 2.0.11 跑起来且行为可对比（P0–P4），再吃架构红利（P5–P7），最后灰度收口（P8）。**
> P0–P4 是不可拆分的整体——拆开必然出现「一半 str 一半 block」的最毒中间态。

### P0 基线冻结与护栏（0.5 人日）

| 项 | 内容 |
|---|---|
| 任务 | 1. 建分支 `feat/agentscope-2`；`pip freeze > data/baseline/pip-1.0.16.txt`。<br>2. 存档四项基线：`pytest -q`（164）、`python tools/replay_shadow.py`、`python tests/eval_rag_tree.py`（40 题）、`python cli.py health`。<br>3. 新增**契约快照测试** `tests/test_msg_contract_snapshot.py`：8 类典型输入下，把 IntentionAgent / OrchestrationAgent 的 content JSON 落盘 `tests/snapshot/*.json`，锁死字段结构（意图 6 大类、agent_schedule、sources、proactive_question）。<br>4. 新增**静默点门禁** `tests/test_no_raw_msg_content_access.py`：静态扫描全仓，命中即 fail —— `import AgentBase`、`agentscope.init`、`json.loads(<...>.content)`、`str(content)`、`.content[` 切片、`Msg(content=<裸str>)`、`model([{`；白名单只允许 `utils/as_compat.py`。 |
| 验收 | 四项基线写入 `docs/agentscope-2-baseline.md`；**门禁在 1.0.16 下必须红**（证明它抓得住问题，不是空转） |
| 回滚 | 无生产改动，天然安全 |

> 先建「在旧版本下会红」的门禁，是本计划最重要的工程手段：把 §1.2 的静默风险提前变成编译期风险。

### P1 协议层与依赖切换（1 人日）

| 项 | 内容 |
|---|---|
| 任务 | 1. `requirements.txt`：`agentscope==1.0.16` → `agentscope==2.0.11`；`pip install --dry-run` 核对 `setuptools>=69,<82`（milvus_lite 约束）与新增 `mcp>=2.0.0` 的解算结果。<br>2. 新建 **`utils/as_compat.py`**（骨架见 §5）：`setup / build_chat_model / mk_msg / msg_text / msg_json / as_messages / chat_text`。<br>3. `config_agentscope.py`：`agentscope.init(project, name, logging_level)` → `agentscope.setup_logger(level)`（**保持 `init_agentscope()` 函数名与幂等语义**，18 处引用零改动）；`get_model_config()` 改为 credential/model/parameters 三段。<br>4. `utils/llm_response.extract_llm_text` 委托 `as_compat.chat_text`（保留 MiMo thinking-only 容错，删 1.x dict 分支）。 |
| 验收 | `agentscope.__version__ == "2.0.11"`；as_compat 单测覆盖 5 类 content 形态（str / blocks / dict 负载 / 空 / 仅 thinking） |
| 回滚 | 纯新增 + 依赖行，单提交 revert |

### P2 消息文本通道收口（1.5 人日）⚠️ 关键阶段

| 项 | 内容 |
|---|---|
| 规模 | 78 处 `Msg(` · 39 处 `json.loads(.content)` · 14 处 `str(content)` · 3 处 content 切片/求长度 · 2 处 `content={}` |
| 任务 | 1. **最高优先**：`agents/intention_agent.py:996-1012` —— `msg.content[:500]`、`len(msg.content)`、`x[-1].content` 全改 `msg_text(...)`，并加 `assert isinstance(user_query, str)`。这是唯一会造成「能跑但准确率静默下降」的点。<br>2. `agents/orchestration_agent.py:362-364`：`json.loads(response.content)` → `msg_json(response, {})`；`{"output": response.content}` → `{"output": msg_text(response)}`。<br>3. `cli.py:209,293` 同改。<br>4. 13 个 `.claude/skills/*/script/agent.py`：删各自 `try/except ImportError` shim 与 `_mk_msg` 副本，统一 `from utils.as_compat import mk_msg, msg_text, msg_json`；入口 `user_query = str(content)` → `msg_text(...)`。<br>5. 8 个测试文件（含 `tests/test_decision_integration.py`）同步换。<br>6. 打开 P0 门禁，清零全部违规。 |
| 验收 | 门禁绿；`pytest -q` 全绿；**快照逐字段 diff = 0**；`python tests/test_cli_qa.py` 端到端通过 |
| 回滚 | 按文件分组提交，可单文件 revert |

### P3 模型层与调用入参（1 人日）

| 项 | 内容 |
|---|---|
| 任务 | 1. 14 处构造 → `as_compat.build_chat_model(cfg)`，产出 `OpenAIChatModel(credential=OpenAICredential(api_key, base_url), model=..., parameters=OpenAIChatModel.Parameters(max_tokens=, temperature=), stream=, max_retries=, retry_delay=, client_kwargs=)`。<br>2. `SCENARIO_TOKENS` **保持按调用覆盖**：实测 `__call__(..., **kwargs)` → `_call_api(**generate_kwargs)` 透传，`await model(msgs, max_tokens=...)` 仍有效，不必拆多模型实例（需在 MiMo/阿里云 compatible-mode 回归，见 R4）。<br>3. 18 处 dict 入参 → `as_messages([...])` 产 `list[Msg]`。<br>4. `utils/llm_failover.py`：鸭子调用不变（`await self._model(idx)(*args, **kwargs)` 成立），仅换构造点；补「空 content 也判失败」。<br>5. 同步 `utils/llm_resilience.py:108`、`rag_core/tree_builder.py:257`、`context/memory_manager.py:212`、`verify_llm.py:47`。 |
| 验收 | `python verify_llm.py` 主/备通道各 3 轮与 1.x 一致；`python tools/bench_decision.py`（24 条金标准）无回归 |
| 回滚 | 构造集中在 `as_compat.build_chat_model`，单点回滚 |

### P4 Agent 基类收编（1 人日）

| 项 | 内容 |
|---|---|
| 任务 | 1. 新建 `agents/base.py::SkillAgentBase`：`__init__(self, name, **kw)` + `async __call__(self, x)` 委托 `reply` + `async reply` 抽象，成为全项目唯一定义（**取代框架 AgentBase**）。<br>2. 15 处 `class Xxx(AgentBase)` → `class Xxx(SkillAgentBase)`。<br>3. `agents/lazy_agent_registry.py:15` 的 AgentBase 导入（isinstance 与 `Dict[str, AgentBase]` 注解）→ 换 `SkillAgentBase`，强类型注解改 `Protocol`（只要求 `async reply`）降低耦合。<br>4. 删除 ask-question 内的重复 shim。 |
| 验收 | 插件发现/懒加载测试全绿；`python cli.py health`；10 个 Skill 装载数与 P0 一致 |
| 回滚 | `agents/base.py` + 继承点批量 revert |

> **P0–P4 = 最小可用升级（5 人日）：完成后系统跑在 2.0.11 且行为与 1.x 对齐。** P5–P7 是架构红利，可按评审结论裁剪。

### P5 Skill → 原生工具运行时（2.5 人日）— ✅ 加法式桥接完成（按用户决定停在此，typed handler 不做）

| 项 | 内容 |
|---|---|
| 任务 | 1. 每个 Skill 拆两层：`script/handlers.py`（纯业务函数，零框架依赖）+ `script/agent.py`（薄壳，只做 Msg ↔ handler 转换）。<br>2. handler 用 `FunctionTool(func, name, description, input_schema, is_read_only=..., is_concurrency_safe=...)` 注册进 `Toolkit(tools=[...], skills_or_loaders=[LocalSkillLoader(skills_root, scan_subdir=True)])`。<br>3. `data/plugin_config.json` 启停改为 `ToolGroup` 过滤，保留热加载与 `/api/memory` 插件管理契约。<br>4. 待实测 Q1：原生 SKILL.md frontmatter 与 `utils/skill_loader.py` 字段差异（§9）。<br>5. 每个 handler 补 1 个纯函数用例（脱离 Msg）。 |
| 验收 | skill_loader 测试绿；10 个 Skill 经 Toolkit 链跑通；意图→工具映射与 `tests/test_orchestration.py` 一致 |
| 收益 | 并发调度交给框架、只读工具自动豁免权限、SKILL.md 与官方格式对齐（可从 hub 装第三方 skill） |
| **已完成（2026-11-06）** | `agents/skill_toolkit.py`：`build_skill_toolkit()` 把 13 个 SKILL.md 交给原生 `LocalSkillLoader` 作指令层，并把 13 个 Skill 的 `reply()` 桥接成 `FunctionTool`（返回 `ToolChunk`）作工具层。实测 **工具 13/13、指令 13/13**；`tests/test_skill_toolkit.py` 4 项（含 `Toolkit.call_tool` 端到端 JSON 往返）。**现有 agent.py 零改动**，属纯加法 |
| **待做（P5b）** | 对翻译/汇率/搜索类 Skill 抽 typed handler（显式参数 + JSON schema），替代通用 `payload` 桥；其余 Skill 保持通用桥 |

### P6 结构化输出与编排升级（2 人日）— ✅ P6a 已完成；P6b（Pipeline/SOP）判定不适用

> **P6a 实施记录（2026-11-06）**：2.x 的 `reply(structured_schema)` 是 `Agent` 的能力，本项目编排层是自研的（IntentionAgent 直调模型），
> 因此改用同机制的底层实现——**强制单工具调用 + JSON schema**：`as_compat.build_tool_schema / extract_tool_call_json` +
> `IntentionAgent` 的 `tools=`/`tool_choice=submit_intent`（`ALIGO_INTENT_STRUCTURED=1` 默认开，异常自动回退文本解析）。
> 端点实测：glm/compatible-mode **支持 auto/required/forced 三种 tool_choice**（返回 thinking + tool_call 块）；
> **不支持 `response_format`**（400: volcengine/litellm 拒绝该参数）——所以 6 级 JSON 降级保留为兜底。
> 测试：`tests/test_intention_structured.py`（tool_call 优先 + 文本兜底，2 passed）+ 真实端点意图解析成功。
> 埋点：`[INTENT] 输出来源=tool_call|text`。

| 项 | 内容 |
|---|---|
| 任务 | 1. `IntentionAgent` 改 `reply(inputs, structured_schema=IntentDecision)`，`IntentDecision` 复用 `utils/decision_schema.py` 的 13 类意图定义；`json_parser` 降为「端点不支持 tool_choice」兜底。<br>2. `OrchestrationAgent` 保留自研优先级调度，同时把同优先级并行改为可选 `TeamPipeline(leader, members, reset_members)`，**影子对比**后决定去留。<br>3. plan-trip 评估 `SOP/SOPEngine` 与 `GoalPipeline(executor, verifier, verifier_reset_context, max_iters, max_retries)`：用「里程碑 + 逐步校验」替代手写多轮修补。<br>4. `TracingMiddleware`（OTel）替换自研 `[TIMING]` print 埋点；保留 `data/decision_shadow/*.jsonl`。 |
| 验收 | 24 条金标准 + 40 题 RAG 指标不低于 P0；JSON 解析失败告警下降 ≥ 50% |

### P7 事件流、权限与决策层退役（3 人日）— ⛔ 判定不适用/阻塞（见 §11）

| 项 | 内容 |
|---|---|
| 任务 | 1. `server/routes/chat.py` 的 SSE 改由 `reply_stream` + `EventType` 驱动：`TEXT_BLOCK_DELTA→增量文本`、`THINKING_BLOCK_DELTA→thinking 帧`、`TOOL_CALL_START/END→工具卡片`、`TOOL_RESULT_TEXT_DELTA→结果`、`REPLY_END/COMPLETED→done`、`EXCEED_MAX_ITERS/USER_INTERRUPT→错误帧`；`web/src/api/client.ts` **只加不改**（旧事件名保留）。<br>2. 权限门控：`PermissionMode` 默认 `EXPLORE`（只读放行），副作用工具 `ASK` → `REQUIRE_USER_CONFIRM` → 前端确认卡片 → `USER_CONFIRM_RESULT` 回流，配 `ReActConfig(stop_on_reject=True)`。<br>3. 偏好澄清改用原生 `AskUser`（多选）替换自研 `proactive_question`（旧字段保留一版）。<br>4. 决策层：`decision_engine` → `JevClassifierModel`；`decision_router` 内部委托 `ModelRouterMiddleware`；四档语义与熔断保留；`ALIGO_DECISION_MODE=off` 时零调用、不装 `classifier-jev` extras。<br>5. 上下文治理：`ContextConfig` + `compress_context()` + `Offloader`，长行程中间产物落盘。 |
| 验收 | SSE 帧序列与旧版逐帧 diff（除新增帧）；权限拒绝路径有测试；影子一致率 ≥ 基线；`GET /api/health` 的 `decision_layer` 字段语义不变 |

### P8 灰度、评测与收口（1.5 人日）— ✅ 已完成（docs/as2-ab-report.md）

| 项 | 内容 |
|---|---|
| 任务 | 1. 双跑开关 `ALIGO_AS_VERSION=v2`：≥200 条真实会话在 1.0.16（旧 venv）与 2.0.11 分别跑，比对意图、sources、耗时、token。<br>2. 门禁：意图一致率 ≥ 97%、RAG 命中 ≥ 基线、P95 劣化 ≤ 10%。<br>3. 文档收口：`CLAUDE.md`（版本 + 架构段 + 「禁止混用 1.x 写法」）、`docs/agentscope-2-migration.md` 踩坑实录、`docs/CHANGELOG.md`。<br>4. 清理遗留 shim；`experiments/as211_probe*.py` 升级为 `tools/probe_wheel.py`（wheel API 探测通用工具，留给下次升级复用）。 |
| 验收 | 指标报告 + **回滚预案实测演练**（一条命令切回 1.0.16） |

### 工时与排期

| 阶段 | 人日 | 内容 |
|---|---|---|
| P0 | 0.5 | 基线冻结 + 门禁测试 |
| P1 | 1.0 | as_compat + 依赖切换 |
| P2 | 1.5 | 消息文本通道收口（56 个静默点） |
| P3 | 1.0 | 模型层与调用入参 |
| P4 | 1.0 | Agent 基类收编 |
| **小计（必做）** | **5.0** | **2.0.11 可运行且行为对齐** |
| P5 | 2.5 | Skill → Toolkit/FunctionTool |
| P6 | 2.0 | structured output + Pipeline/SOP |
| P7 | 3.0 | EventType SSE + 权限 + 决策层退役 |
| P8 | 1.5 | 灰度双跑 + 收口 |
| **合计** | **15.5** | 3 个迭代：① P0–P2 ② P3–P5 ③ P6–P8 |
---

## 5. 协议层设计（`utils/as_compat.py` 骨架，可直接落地）

```python
"""AgentScope 2.0.11 适配层 —— 全项目唯一允许接触 content 块结构的模块。"""
from __future__ import annotations
import json
from typing import Any, Iterable

from agentscope.message import Msg, UserMsg, AssistantMsg, SystemMsg, TextBlock


def setup(logging_level: str = "INFO") -> None:
    """替代 agentscope.init(project=, name=, logging_level=)。
    2.x 的 init/project/name（Studio 埋点语义）已不存在；setup_logger(level, filepath) 是唯一对应物。
    """
    from agentscope import setup_logger
    setup_logger(level=logging_level)          # 合法值：INFO/DEBUG/WARNING/ERROR/CRITICAL


def mk_msg(name: str, content: Any, role: str = "assistant", metadata: dict | None = None) -> Msg:
    """统一消息构造：str / dict / list / None 都能接，内部转块列表。
    非字符串业务负载一律 json.dumps 进 TextBlock；metadata 保留原始 dict，下游可零解析取用。
    """
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    elif isinstance(content, list) and content and all(
        isinstance(c, (TextBlock, dict)) and getattr(c, "type", None) or (isinstance(c, dict) and c.get("type"))
        for c in content
    ):
        return _route(role, name, content, metadata)          # 已经是块列表，透传
    else:
        text = json.dumps(content, ensure_ascii=False)         # dict / list 业务负载
    factory = {"user": UserMsg, "system": SystemMsg}.get(role, AssistantMsg)
    return factory(name=name, content=text, metadata=metadata or {})


def msg_text(msg: Any, fallback: str = "") -> str:
    """把消息/响应取成纯文本。2.x 下 msg.content 是块列表，禁止切片与 str()。
    thinking-only 响应返回 fallback（保留 llm_response.py 对 MiMo 的特判语义）。
    """
    if msg is None:
        return fallback
    get = getattr(msg, "get_text_content", None)
    if callable(get):
        t = get()
        if t and t.strip():
            return t
    c = getattr(msg, "content", None)
    if isinstance(c, str):
        return c or fallback                                   # 兼容 1.x / 测试桩
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict):
                parts.append(b.get("text", ""))
            else:
                parts.append(getattr(b, "text", ""))
        joined = "".join(p for p in parts if p)
        return joined or fallback
    return fallback


def msg_json(msg: Any, default: Any = None) -> Any:
    """从消息文本健壮解析 JSON（内部复用 utils.json_parser.robust_json_parse）。"""
    from utils.json_parser import robust_json_parse
    text = msg_text(msg)
    if not text:
        return default
    try:
        return robust_json_parse(text, fallback=default)
    except Exception:
        return default


def as_messages(items: Iterable[Any]) -> list[Msg]:
    """把 1.x 风格 list[dict]（{"role","content"}）转成 2.x 要求的 list[Msg]。
    迁移期用它包住 18 处旧调用，稳定后逐步直书 UserMsg/SystemMsg。
    """
    out: list[Msg] = []
    for it in items:
        if isinstance(it, Msg):
            out.append(it)
            continue
        role = (it.get("role") if isinstance(it, dict) else None) or "user"
        text = it.get("content") if isinstance(it, dict) else str(it)
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        out.append({"user": UserMsg, "system": SystemMsg}.get(role, AssistantMsg)(name=role, content=text))
    return out


def build_chat_model(cfg: dict, *, stream: bool = False, **overrides):
    """1.x 关键字（model_name/api_key/base_url/generate_kwargs/client_kwargs）→ 2.x（credential/model/parameters）。
    全项目唯一模型构造点；llm_failover 的多通道共用此工厂。
    """
    from agentscope.credential import OpenAICredential
    from agentscope.model import OpenAIChatModel
    gk = {**cfg.get("generate_kwargs", {}), **(cfg.get("overrides") or {})}
    return OpenAIChatModel(
        credential=OpenAICredential(api_key=cfg["api_key"], base_url=cfg.get("base_url")),
        model=overrides.get("model", cfg["model_name"]),
        parameters=OpenAIChatModel.Parameters(
            max_tokens=gk.get("max_tokens"),
            temperature=gk.get("temperature"),
            thinking_enable=gk.get("enable_thinking"),
        ),
        stream=overrides.get("stream", stream),
        max_retries=cfg.get("max_retries", 2),
        retry_delay=cfg.get("retry_delay", 1.0),
        client_kwargs=cfg.get("client_kwargs") or {},
    )


def chat_text(resp: Any, fallback: str = "") -> str:
    """从 ChatResponse / Msg / dict 中提取纯文本（替代 extract_llm_text 的 2.x 实现）。"""
    t = getattr(resp, "text", None)
    if isinstance(t, str) and t.strip():
        return t
    return msg_text(resp, fallback)


def _route(role, name, blocks, metadata):
    factory = {"user": UserMsg, "system": SystemMsg}.get(role, AssistantMsg)
    return factory(name=name, content=blocks, metadata=metadata or {})
```

设计要点：

- `as_messages` 是迁移期的「语义等价转换器」：一次改 18 处调用但行为不变；稳定后再直书工厂函数。
- `msg_text` 对 thinking-only 返回 fallback —— 与现行 `extract_llm_text` 行为逐位对齐，保证 P2 快照零 diff。
- `build_chat_model` 集中处理 `Parameters`（嵌套类）与 `credential` 的三段式拆分，`llm_failover` 复用同一工厂。
- `metadata` 通道：业务负载 dict 同时放进 `Msg.metadata`，server 层可取结构化数据而不再解析文本。

---

## 6. 风险登记册

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | **静默文本损坏**：`str(content)`/`content[:N]` 把块 repr 塞进 prompt，测试绿但线上答非所问 | 高 | 严重 | P0 静态门禁 + P2 集中收口 + 快照比对 + `msg_text` 唯一出口 |
| R2 | 记忆摘要等 system/user 消息混入非法块被角色校验拒绝（`_assert_user_content_blocks` ValueError） | 中 | 中 | 统一走 `mk_msg`；记忆摘要用 `SystemMsg`（仅允许 text 块） |
| R3 | MiMo / 阿里云 compatible-mode 端点在新参数形态下行为漂移（`parameters` 嵌套类 vs 旧 `generate_kwargs`；`thinking_enable` 键名） | 中 | 严重 | P3 用 `verify_llm.py` 双跑；保留 `client_kwargs`/`extra_body` 逃生通道；`enable_thinking` 特判留在 handler 层 |
| R4 | 按调用传 `max_tokens` 在个别端点被忽略（`**kwargs` 透传已实测存在，但端点行为无法静态保证） | 低 | 中 | P3 逐场景回归 `SCENARIO_TOKENS`；不行就拆「每场景一个 Parameters 的模型实例」，工厂已支持 |
| R5 | `mcp>=2.0.0` 抬升依赖树与 `setuptools<82`（milvus_lite）冲突 | 中 | 中 | P1 `pip install --dry-run` 预解；本项目不用 mcp，冲突则锁定 mcp 或走 extras 精简 |
| R6 | `agentscope.init` 的 project/name（Studio 埋点）语义消失，日志上下文变薄 | 高 | 低 | `setup_logger(level, filepath)` + 自有 logging Formatter 覆盖；P0 记录丢失项 |
| R7 | SSE 事件粒度变细，前端帧序列不兼容 | 中 | 严重 | P7 只加不改；逐帧 diff 测试；灰度期 1.x/2.x 后端共存 |
| R8 | `structured_schema` 在 MiMo 上触发 tool_choice 冲突（2.x 内部有 fallback 异常清单，但端点差异仍在） | 中 | 中 | P6 保留 `json_parser` 六级降级为兜底；用 24 条金标准验收 |
| R9 | 决策层从自研 `POST /v1/decision` 换 `JevClassifierModel` 后协议不一致 | 中 | 严重 | 默认 `ALIGO_DECISION_MODE=off`；影子期双写日志，`replay_shadow.py` 一致率达标才切 primary |
| R10 | P2 的 78+39+14 处纯手工收口，工时易低估 | 高 | 中 | P0–P4 单独立项不与 P5–P7 混排；门禁防「半途合入」；机械替换脚本化（sed 式 + 人工复核） |
| R11 | 1.x/2.x 混写（官方警告 Do not mix；AI 辅助编码易混） | 高 | 中 | CLAUDE.md 加禁令条目 + §3.1 四条硬约束进 CI 门禁 |
| R12 | 回滚需求 | — | — | `data/baseline/pip-1.0.16.txt` + 双 venv + `ALIGO_AS_VERSION` 开关；P1–P4 每阶段独立可 revert |

---

## 7. 验收标准（Definition of Done）

1. `requirements.txt` 为 `agentscope==2.0.11`，`pip check` 干净，Python 3.12.8。
2. `pytest -q` ≥ 164 全绿，且新增 3 个门禁（契约快照 / 无裸 content 访问 / as_compat 单测）全绿。
3. 全仓静态扫描 0 命中：`AgentBase` / `agentscope.init` / `json.loads(...content)` / `str(content)` / `Msg(content=<裸str>)` / `model([{...}])`。
4. `python cli.py` 与 `server/app.py` + `web/` 端到端：意图→调度→Skill→记忆链路结果与 P0 基线**逐字段对齐**（8 类输入快照 diff = 0）。
5. `python tests/eval_rag_tree.py` 40 题指标 ≥ 基线；`python tools/replay_shadow.py` 影子一致率 ≥ 基线；`cli.py health` 正常且 `decision_layer` 字段语义不变。
6. `docs/`：本计划更新为「实施记录 + 踩坑」；`CLAUDE.md` 版本与架构段同步。
7. 回滚脚本 `tools/rollback_agentscope_1.ps1` 实测可用。

## 8. 明确不做（本期范围外）

- 不引入 `agentscope.app.create_app` 全套 agent-service（storage/channel/hub/多租户），自有 FastAPI + React 契约稳定。
- 不引入 Docker/K8s/E2B/Daytona workspace 沙箱（Windows 开发机不匹配；权限用 `PermissionMode` 即可）。
- 不引入 `agentscope.tui` / `realtime` / `asr` / `channels`（飞书/Discord/钉钉）与官方 WebUI。
- 不迁移 `data/memory/*.json` 到 Mem0/ReMe（可作后续旁路实验）。
- 不改前端事件名（只加不改）。

---

## 9. 评审前待实测清单（4 项，建议 0.5 人日 spike 一次性解决）

| # | 待验证 | 方式 |
|---|---|---|
| Q1 | `LocalSkillLoader(directory, scan_subdir=True)` 能否直接吃 `.claude/skills/*/SKILL.md`；frontmatter 字段与 `utils/skill_loader.py` 的差异 | 临时 venv 装 2.0.11，对 10 个 skill 装载并打印解析 diff |
| Q2 | MiMo/compatible-mode 下 `structured_schema` 是否走通（tool_choice 冲突与内部 fallback 是否触发） | `Agent.reply(msg, structured_schema=IntentDecision)` 跑 24 条金标准 |
| Q3 | `AgentState`(session_id/summary/context/...) 与 `context/` 三层记忆能否无损互转 | 写 `state ↔ MemoryManager` 双向映射草稿测试 |
| Q4 | `PermissionMode=EXPLORE` 对「只读放行、副作用 ASK」的判定粒度（`is_read_only` 是否被 `PermissionEngine` 采信） | place-search 与 expense-tracker 各跑一次，观察 `REQUIRE_USER_CONFIRM` |

> spike 结论直接回写 §3.2 / §5 / §6，再定 P5–P7 最终形态。**P0–P4 不依赖 spike，可立即开工。**

---

## 10. 附录：2.0.11 实测 API 速查（已核对源码，可直接照抄）

```python
# 顶层（注意：没有 init()）
from agentscope import logger, setup_logger, set_id_factory, set_timestamp_factory, __version__
# setup_logger(level: str, filepath: str | None = None)   # INFO/DEBUG/WARNING/ERROR/CRITICAL

# 消息
from agentscope.message import (Msg, UserMsg, AssistantMsg, SystemMsg, Usage,
    TextBlock, ThinkingBlock, HintBlock, ToolCallBlock, ToolResultBlock, DataBlock,
    Base64Source, URLSource, ContentBlock, ContentBlockTypes)
# Msg.content: list[ContentBlock]；msg.get_text_content(sep) / get_content_blocks(type) / has_content_blocks(type)
# UserMsg: str | list[TextBlock|DataBlock]；SystemMsg: str | list[TextBlock]；AssistantMsg: str | list[ContentBlock]

# 模型（本项目主路径）
from agentscope.credential import OpenAICredential          # fields: type, api_key, organization, base_url
from agentscope.model import OpenAIChatModel
OpenAIChatModel(credential, model, parameters, stream, max_retries, retry_delay,
                context_size, formatter, client_kwargs, extra_body)
OpenAIChatModel.Parameters: max_tokens, thinking_enable, reasoning_effort, temperature,
                            top_p, parallel_tool_calls, voice
await model(messages: list[Msg], tools=None, tool_choice=None, **kwargs)
    -> ChatResponse(content, is_last, usage, finished_reason, metadata) | AsyncGenerator[ChatResponse, None]
# **kwargs 透传 _call_api(**generate_kwargs)：按调用覆盖 max_tokens 有效（SCENARIO_TOKENS 机制保留）

# Agent（取代 AgentBase）
from agentscope.agent import Agent, A2AAgent, ContextConfig, ReActConfig, ModelConfig, InjectionConfig
Agent(name, system_prompt, model, toolkit, middlewares, state, offloader,
      model_config, context_config, react_config, injection_config)
    .reply(inputs, structured_schema) / .reply_stream(inputs, structured_schema, yield_final_msg)
    .observe(msgs) / .compress_context(context_config, instructions)
ReActConfig: max_iters, structured_output_grace_iters, stop_on_reject, interruption_message,
             interruption_raise_cancelled_error
ContextConfig: trigger_ratio, reserve_ratio, context_buffer_ratio, compression_prompt, summary_template,
               summary_schema, tool_result_limit, compression_fallback_to_truncation,
               compression_tool_enabled, max_image_num
ModelConfig: max_retries, fallback_model

# 工具 / Skill
from agentscope.tool import (Toolkit, FunctionTool, ToolBase, MCPTool, AskUser, ToolGroup,
    Bash, PowerShell, Read, Write, Edit, Glob, Grep, TaskCreate, TaskGet, TaskList, TaskUpdate, LocalBackend)
Toolkit(tools, skills_or_loaders, mcps, tool_groups, meta_tool_response_template, skill_instruction_template)
FunctionTool(func, name, description, input_schema, is_concurrency_safe, is_read_only,
             is_state_injected, middlewares, permission)
from agentscope.skill import Skill, SkillLoaderBase, LocalSkillLoader   # LocalSkillLoader(directory, scan_subdir)

# 事件（SSE 用）
from agentscope.event import EventType
# REPLY_START/END · MODEL_CALL_START/END · TEXT_BLOCK_* · THINKING_BLOCK_* · DATA_BLOCK_*
# TOOL_CALL_START/DELTA/END · TOOL_RESULT_TEXT_DELTA/DATA_DELTA/END · HINT_BLOCK
# REQUIRE_USER_CONFIRM · USER_CONFIRM_RESULT · REQUIRE_EXTERNAL_EXECUTION · EXTERNAL_EXECUTION_RESULT
# USER_INTERRUPT · EXCEED_MAX_ITERS · COMPLETED · INTERRUPTED · CUSTOM

# 中间件
from agentscope.middleware import (MiddlewareBase, ModelRouterMiddleware, ReplyBudgetControlMiddleware,
    RAGMiddleware, Mem0Middleware, ReMeMiddleware, AgenticMemoryMiddleware, TracingMiddleware, TTSMiddleware)
# MiddlewareBase 钩子: on_reply, on_reasoning, on_acting, on_check_permission, on_model_call,
#                      on_compress_context, on_system_prompt, list_tools
ModelRouterMiddleware(classifier_model, candidates, instructions)
ReplyBudgetControlMiddleware(token_budget, input_token_weight, output_token_weight, hint_message)
RAGMiddleware(knowledge_bases, parameters, rerank_model)

# 决策层替换
from agentscope.classifier import (JevClassifierModel, OpenAIClassifierModel, BinaryQuestion,
    ChoiceQuestion, ScoreQuestion, ClassifierResponse, ClassifierUsage)
JevClassifierModel(credential, model, parameters, timeout, max_retries, retry_delay)

# 编排 / 权限 / 状态 / 工作区 / RAG
from agentscope.pipeline import GoalPipeline, TeamPipeline, TeamMember
GoalPipeline(executor, verifier, verifier_reset_context, max_iters, max_retries)
TeamPipeline(leader, members, reset_members)
from agentscope.sop import SOP, SOPStep, SOPEngine, SOPRunState, VerificationResult
from agentscope.permission import (PermissionEngine, PermissionRule, PermissionMode,
    PermissionContext, PermissionDecision, PermissionBehavior)
# PermissionMode: DEFAULT / EXPLORE / ACCEPT_EDITS / BYPASS / DONT_ASK / ALLOW / ASK / DENY / PASSTHROUGH
from agentscope.state import AgentState, Task, TaskContext, ReplyContext, ToolContext
# AgentState: session_id, summary, context, reply_context, permission_context, tool_context, tasks_context, middle_context
from agentscope.workspace import LocalWorkspace, Offloader          # 不引入容器沙箱
from agentscope.rag import (KnowledgeBase, VectorStoreBase, TextParser, WordParser, ExcelParser,
    PDFParser, ApproxTokenChunker)
```

---

## 11. P6b / P7 适用性评估（2026-11-06 实测结论）

结论：**计划中 P6b 与 P7 的四项能力都依赖 2.x `Agent` 运行时，本项目编排层是自研的，因此判定为"不适用"，不是"未完成"。**

| 计划项 | 需要的 2.x 载体 | 本项目现状 | 判定 | 若强行落地的代价 |
|---|---|---|---|---|
| P6b `GoalPipeline` / `TeamPipeline` / `SOP` | `Agent` 实例作为 executor/verifier/leader/member | 编排是 `OrchestrationAgent` + `asyncio.gather`（自研优先级调度） | **不适用** | 需把编排核心重写为 2.x Agent 驱动（≈ P0–P4 同等工作量） |
| P7 EventType SSE(`reply_stream`) | `Agent.reply_stream` 产出 `AgentEvent` | 各 Skill 是自定义类，只实现 `reply()`，无事件流 | **不适用** | 同上；只改事件名映射无功能收益 |
| P7 权限(`PermissionEngine`) / `AskUser` / HITL | 权限引擎在 Agent 的 acting 循环内判定 | 无 Agent 循环，工具调用由我们的调度器发起 | **不适用** | 需先有 2.x Agent 运行时 |
| P7 决策层换 `classifier.JevClassifierModel` | `agentscope[classifier-jev]`(typesafe_sdk) + TypeSafe 兼容端点 | 自研 `POST /v1/decision` 私有协议客户端（含熔断/影子/四档） | **阻塞**（需确认端点协议） | 需先确认 NeoHorse 端点是否 TypeSafe 兼容；否则要换服务商 |

### 为什么这不是"偷懒"

1. 这四项的共同前提都是「应用跑在 2.x `Agent` 的 ReAct 循环里」，而本项目的架构优势恰恰是**确定性的自研编排**（意图→优先级调度→并行 Skill），
   把它换成 LLM 驱动的 Agent 循环会牺牲可预测性与成本。
2. 与升级目标直接相关的部分（消息协议、模型网关、工具运行时、结构化输出）已经全部落地并验证（见 §4 P0–P6a）。
3. 因此本计划的"做完"= P0–P6a 全部完成 + P6b/P7 有据可查地判定不适用 + P8 证据留存。

### 如果将来想做（可选路线）

1. 保留现有编排，**新增**一个 2.x `Agent` 作为「单个 Skill 内部的多步执行器」（例如 plan-trip 的行程生成），其余 Skill 仍是 `reply()` 形态；
2. 决策层先做协议探测：用 `typesafe_sdk` 打一发 NeoHorse 端点，通了再换 `JevClassifierModel`；
3. 届时再启用 EventType SSE（只在那个 Agent 的流式接口上）。