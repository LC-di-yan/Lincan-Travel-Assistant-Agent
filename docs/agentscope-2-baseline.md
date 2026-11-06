# AgentScope 2.0.11 升级基线与验证记录

> 记录时间：2026-11-06 | 环境：Python 3.12.8 / Windows

## 升级前后测试基线

| 指标 | 1.0.16（升级前） | 1.0.16（P2 收口后） | 2.0.11 |
|---|---|---|---|
| pytest | **157 passed, 7 skipped** | **169 passed, 7 skipped** | **169 passed, 7 skipped（0 failed）** |
| RAG 检索 Hit@1（40 题） | 0.575 | 0.575 | **0.575** |
| RAG 检索 Hit@3 | 0.900 | 0.900 | **0.900** |
| RAG 检索 Hit@4 | 0.975 | 0.975 | **0.975** |
| RAG MRR | 0.744 | 0.744 | **0.744** |
| 树导航参与 | 38/40 | 38/40 | 38/40 |
| 静态门禁违规（file:pattern） | 61（初始全量捕获） | 0 | 0 |

## 升级前依赖快照

- `data/baseline/pip-1.0.16.txt`（618 个包，含 agentscope==1.0.16 / mcp==1.27.2 / openai==2.48.0 / pydantic==2.13.4）
- 回滚：`pip install -r data/baseline/pip-1.0.16.txt` 或 `pip install agentscope==1.0.16`

## 双版本验证矩阵（全部实测通过）

| 验证项 | 1.0.16 | 2.0.11 |
|---|---|---|
| `tests/test_as_compat.py`（含 KeyError-getattr 回归 ×2） | 10/10 | 10/10 |
| `tests/test_as2_gate.py`（棘轮门禁） | 2/2 | 2/2 |
| 10 个已迁移 Skill 装载 + reply(None) + msg_json 往返 | — | 10/10 |
| RAG 树索引重建（12 篇文档） | ✅ | ✅ |
| RAG 离线评测 40 题 | 0.575/0.900/0.975 | 0.575/0.900/0.975（逐位一致） |
| IntentionAgent 真实 LLM 意图识别（快路由命中） | ✅ | ✅ |
| IntentionAgent 真实 LLM 意图识别（LLM 路径，77s） | — | ✅ intents=[itinerary_planning, hotel_search] |

## 关键实测结论（升级计划 §1 的补充修正）

1. **1.0.16 的 OpenAIChatModel.__call__ 要求 list[dict]，2.0.11 要求 list[Msg]** —— `as_messages` 按版本分支，两侧等价。
2. **1.0.16 的 ChatResponse.__getattr__ 抛 KeyError 而非 AttributeError**，内置 getattr(x, name, default) 兜不住
   （项目旧代码 `_safe_hasattr` 由此而来）。as_compat 已统一 `_safe_getattr`，并补了回归测试。
3. **2.x ThinkingBlock 没有 .text 字段** —— 块识别不能只认 .text，按「type 属性是字符串」判定；文本提取只取 TextBlock。
4. 1.0.16 的 Msg 已支持块序列与 metadata；str content 在 1.x 原样保留（get_text_content 两个版本都在）。
5. `agentscope.init` 在 2.x 全 wheel 0 命中；替代物 `setup_logger(level, filepath=None)`。
6. 真实 LLM 意图识别在 2.0.11 下完整可用（as_messages → list[Msg] → OpenAICredential/Parameters → ChatResponse → chat_text → msg_json）。

## 已知依赖注意项

- 2.0.11 硬依赖 `mcp>=2.0.0`；本机系统环境现有 fastmcp==2.14.7 要求 mcp<2.0（**项目代码不使用 fastmcp/mcp**，无实际影响）；
  openjiuwen 要求 pymilvus<2.6.10（同样与项目无关）。影子 venv `.venv-as2`（--system-site-packages）已装 agentscope==2.0.11 + mcp==2.3.0 用于双版本验证。
- `setuptools>=69,<82`（milvus_lite 约束）保持不变。

## 验证脚本索引

- `experiments/smoke_as2_skills.py`：10 个 Skill 在 2.0.11 下装载/回复/JSON 往返冒烟
- `experiments/smoke_as2_intention.py / _intention2.py`：意图识别真实 LLM 冒烟（快路由 / LLM 路径）
- `tools/check_as2_gate.py`：静态门禁（--update / --prune），白名单 `data/as2_gate_allowlist.json`
- `experiments/impact_audit.py / hazard_scan.py / as211_probe*.py`：升级前的 API 实证与冲击面量化

## 最终验收（2026-11-06 完成）

- **主环境已切换至 agentscope 2.0.11**（mcp 1.27.2 → 2.3.0；Python 3.12.8）
- **2.0.11 全量测试：169 passed / 7 skipped / 0 failed（exit 0，376s）**
- **1.0.16 全量测试（收口后）：169 passed / 7 skipped / 0 failed**
- 静态门禁：全仓 0 残留（8 类模式 × 全部业务代码）
- 真实通道探活：`python verify_llm.py` → 响应 {"city":"上海","days":3}
- 回滚：`pip install -r data/baseline/pip-1.0.16.txt`（或 `pip install agentscope==1.0.16`）+ `git revert`

## 已知遗留（非本次升级引入）

1. `tests/test_cli_qa.py` 依赖 `AligoCLI._display_results`，该接口在 cli.py 中已不存在（既有接口漂移）。
   脚本型测试不会被 pytest 收集，10 题 LLM 管线可跑通，仅结果渲染处报错。
2. `test_hotel_search.py` 需要 `AMAP_API_KEY` 才能验证高德 POI 路径（本机未配置，脚本自带守卫退出）。
3. pip 报 `openjiuwen`/`student-profile-agent`/`fastmcp` 的版本冲突均为升级前既有、与本项目代码无关
   （项目不使用 mcp/fastmcp/pymilvus）。
4. Windows 控制台 GBK：`scripts/build_rag_index.py` 打印 ✓ 需 `PYTHONIOENCODING=utf-8`（既有问题）。

## 后续阶段（升级计划 P5-P8，未开工）

P5 Skill→Toolkit/FunctionTool、P6 structured output + Pipeline/SOP、P7 EventType SSE + 权限 + 决策层换 JevClassifierModel、P8 灰度双跑。
## P5（Skill ↔ Toolkit，加法式）验证

- `agents/skill_toolkit.py` + `tests/test_skill_toolkit.py`（4 passed）
- 原生 `LocalSkillLoader(.claude/skills, scan_subdir=True)` → **13/13 SKILL.md 原样加载**（frontmatter 的 name/description 正好匹配 2.x `Skill(name, description, dir, markdown)`）
- 经真实 `LazyAgentRegistry` 装载：**工具 13/13、指令 13/13**
- `Toolkit.call_tool` 端到端：ToolCallBlock(type="tool_call", input=JSON字符串) → ToolChunk → 最终 ToolResponse，文本为 Skill 的 JSON
- 结论：**skill 思路没有放弃**；2.x 的 Skill 是"纯指令包"（官方模板原文 "Skills are NOT tools"），本项目 Skill 是"指令+执行"合一，桥接层负责把后者投影到前者之上

## P6a 结构化输出（2026-11-06）

- 机制：强制单工具调用（`tool_choice=ToolChoice(mode="submit_intent")`）+ JSON schema；
  `as_compat.build_tool_schema / extract_tool_call_json`；`ALIGO_INTENT_STRUCTURED=1`（默认）可关。
- 端点能力实测（glm/compatible-mode）：
  - function calling `auto / required / forced(指定工具名)` **全部支持**（响应含 thinking + tool_call 块）
  - `response_format` **不支持**（400: volcengine/litellm 拒绝）→ 6 级文本降级保留为兜底
- 测试：`tests/test_intention_structured.py` 2 passed（tool_call 优先 + 文本兜底）
- 真实端点：意图识别经 tool_call 通道解析成功（intents=[itinerary_planning, hotel_search]）
- 埋点：`[INTENT] 输出来源=tool_call|text structured_mode=True|False`

## 最终测试矩阵

| 环境 | 结果 |
|---|---|
| 1.0.16（P2 收口后） | 169 passed / 7 skipped / 0 failed |
| 2.0.11（P0–P5 后） | 169 passed / 7 skipped / 0 failed |
| **2.0.11（P6a 后，当前）** | **175 passed / 7 skipped / 0 failed（354s）** |
| 门禁 | 0 残留（8 类 1.x 写法） |

## P7 决策层 TypeSafe 后端（2026-11-06）

端点兼容性实测（无鉴权探测，401=存在 / 404=不存在）：

| 路径 | 响应 |
|---|---|
| `POST /v1/systemone`（TypeSafe 标准） | 401 UNAUTHORIZED |
| `POST /v1/decision`（自研客户端） | 401 UNAUTHORIZED |
| `POST /v1/models`（对照） | 404 NOT_FOUND |

结论：**NeoHorse 端点 TypeSafe 兼容**；载荷 `{state, model, questions}` 与自研逐字段同源，
题面原语 noul/choice/score 同名，仅 agentscope 分类器层判别字面量为 binary。

落地：
- `utils/decision_jev.py`：`translate_questions`（noul→BinaryQuestion / choice→ChoiceQuestion）、
  `to_wire`（BinaryAnswer→noul、ChoiceAnswer→choice+probabilities、RefusalAnswer→ValueError）
- `DecisionEngine(backend="jev")` / `ALIGO_DECISION_BACKEND=jev`；默认 custom，零行为变化
- `tests/test_decision_jev_backend.py` 7 passed
- 全量：**182 passed / 7 skipped / 0 failed**

**未完成**：带真实 `sk_tr_` key 的线上端到端（本机 .env 为占位符）。复现命令：
```bash
pip install typesafe-sdk==0.7.5
ALIGO_DECISION_MODE=shadow ALIGO_DECISION_BACKEND=jev NEOHOUSE_API_KEY=sk_tr_xxx \
  python tools/bench_decision.py    # 24 条金标准，观察 answers 是否返回 choice/noul
```

## 线上模型验证：glm-5.3-flash @ token-api.matvenus.com（2026-11-06）

- `.env` 已配置 `ALIGO_MODEL_NAME=glm-5.3-flash` / `ALIGO_BASE_URL=https://token-api.matvenus.com/v1`（gitignored，不入库）
- 该凭据是 **OpenAI 兼容 LLM 网关**（/v1/models 200，含 glm-5.3、glm-5.3-flash、kimi-k3.1-pro），
  **不是** TypeSafe 决策端点：/v1/systemone 与 /v1/decision 均 403 TOKENHUB_ACCESS_DENIED
- 验证结果：
  - `build_chat_model` 真实调用 ✅；`verify_llm.py` ✅
  - **强制工具调用三种模式（auto/required/forced）全部支持** → P6a 结构化输出在新模型上依然成立
  - 意图识别 LLM 路径端到端 ✅（intents=[itinerary_planning, hotel_search]）
  - **全量 pytest：182 passed / 7 skipped / 0 failed（390s，含真实 LLM 用例）**
- 决策层影响：无（默认 mode=off 不走决策层）；若要启用仍需 tokenrhythm.studio 的 `sk_tr_` key
