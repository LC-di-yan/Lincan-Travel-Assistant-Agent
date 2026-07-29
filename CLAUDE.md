# Aligo 智能旅行助手

## 项目概述

多智能体旅行规划系统，基于 AgentScope 框架 + 小米 MiMo 大模型，采用 Plan-and-Execute 架构。

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

# 知识库初始化
python .claude/skills/ask-question/script/init_knowledge_base.py

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
| rag_knowledge | ask-question | RAG 知识库问答 |
| information_query | query-info | 天气/网络搜索 |
| event_collection | event-collection | 行程要素提取 |

### 额外 Skill 插件

| Skill | 说明 |
|-------|------|
| expense-tracker | 费用记录与汇总 |
| currency-converter | 汇率查询（frankfurter.app） |
| translation | 多语言翻译（MyMemory API） |
| visa-info | 签证政策查询（RAG） |

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

## 配置

- `config.py`：LLM / RAG / 稳定性 配置
- `.env`：环境变量（`ALIGO_API_KEY`, `ALIGO_MODEL_NAME`, `ALIGO_BASE_URL`）
- `data/plugin_config.json`：插件启用/禁用

## 关键约定

- 所有子 Agent 的 `reply()` 为 async，需 await
- Agent 使用 `model=model` 传入已创建的 OpenAIChatModel 实例
- Skill 通过 `LazyAgentRegistry` 动态发现，首次调用时加载
- LLM 输出 JSON 解析有 6 种降级策略（`utils/json_parser.py`）
- 熔断器连续失败 5 次后暂停，60 秒后半开恢复（`utils/circuit_breaker.py`）

## 目录速查

| 路径 | 说明 |
|------|------|
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
| `data/models/` | Embedding 模型缓存（首次运行自动下载） |
