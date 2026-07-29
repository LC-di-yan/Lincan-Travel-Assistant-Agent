# Aligo 智能旅行助手 - 测试报告

**项目名称**: Aligo 智能旅行助手（差旅出行助手）
**测试日期**: 2026-06-03
**测试人员**: Aligo Team
**文档版本**: v2.0（含实际执行结果）

---

## 1. 项目概述

Aligo 是基于小米 MiMo 大模型和 AgentScope 框架的多智能体旅行规划系统，采用 Plan-and-Execute 架构，核心能力包括：

- 6 大类意图识别（准确率 90%+）
- 两层记忆系统（短期 + 长期）
- RAG 知识库（Milvus Lite + BGE-small-zh-v1.5）
- 优先级并行调度（asyncio.gather）
- 插件化 Skill 架构（LazyAgentRegistry）
- 熔断器 / 指数退避重试 / 健康检查

---

## 2. 测试执行总览

| 测试模块 | 测试文件 | 用例数 | 通过 | 失败 | 通过率 | 耗时 |
|----------|----------|--------|------|------|--------|------|
| 意图识别 | `test_intention_agent.py` | 4 | 4 | 0 | 100% | ~30s |
| 事项收集 | `test_event_collection_agent.py` | 4 | 4 | 0 | 100% | ~40s |
| 记忆系统 | `test_memory_system.py` | 10 | 10 | 0 | 100% | ~15s |
| RAG 知识库 | `test_rag_agent.py` | 8 | 8 | 0 | 100% | 186s |
| 信息查询 | `test_information_query_agent.py` | 5 | 5 | 0 | 100% | 80s |
| 协调系统 | `test_orchestration.py` | 2 | 2 | 0 | 100% | ~60s |
| 端到端 QA | `test_cli_qa.py` | 10 | 10 | 0 | 100% | 951s |
| **合计** | **7** | **43** | **43** | **0** | **100%** | **~1362s** |

---

## 3. 各模块测试详情

### 3.1 意图识别测试（4/4 通过）

| 编号 | 输入 | 预期意图 | 实际意图 | 置信度 | 结果 |
|------|------|----------|----------|--------|------|
| T-INT-01 | "我要从北京去上海出差3天" | itinerary_planning | itinerary_planning + event_collection | 0.90 | PASS |
| T-INT-02 | "我的家在杭州，我喜欢住汉庭酒店" | preference | preference | 0.95 | PASS |
| T-INT-03 | "我要大机型，靠窗座位" | preference | preference | 0.95 | PASS |
| T-INT-04 | "上海的天气怎么样？" | information_query | information_query | 0.95 | PASS |

**结论**: 意图识别准确率 100%，置信度均在 0.90 以上。

### 3.2 事项收集测试（4/4 通过）

| 编号 | 输入 | 提取项数 | 提取内容 | 结果 |
|------|------|----------|----------|------|
| T-EVT-01 | "我要从北京去上海出差3天" | 4/7 | 出发地:北京, 目的地:上海, 天数:3天, 目的:出差 | PASS |
| T-EVT-02 | "下周一从杭州出发去深圳，周五回来" | 5/7 | 出发地:杭州, 目的地:深圳, 日期:2026-06-08~12, 天数:5天 | PASS |
| T-EVT-03 | "去上海玩" | 2/7 | 目的地:上海, 目的:旅游 | PASS |
| T-EVT-04 | "3月15日从北京到上海，3月18日返回北京，出差" | 7/7 | 全部字段完整提取 | PASS |

**结论**: 事项收集功能正常，能正确处理完整和不完整信息输入。

### 3.3 记忆系统测试（10/10 通过）

| 编号 | 测试项 | 结果 |
|------|--------|------|
| T-MEM-01 | 短期记忆-添加（5条对话） | PASS |
| T-MEM-02 | 短期记忆-查询（最近N轮对话） | PASS |
| T-MEM-03 | 短期记忆-统计（总消息数、最大轮数） | PASS |
| T-MEM-04 | 长期偏好-保存（4项偏好） | PASS |
| T-MEM-05 | 长期偏好-读取 | PASS |
| T-MEM-06 | 行程历史-保存（3条记录） | PASS |
| T-MEM-07 | 行程历史-查询+高频目的地 | PASS |
| T-MEM-08 | 聊天历史-持久化 | PASS |
| T-MEM-09 | LLM总结-异步生成摘要 | PASS |
| T-MEM-10 | 跨会话持久化（新会话访问旧数据） | PASS |

**结论**: 两层记忆系统功能完整，短期记忆会话隔离、长期记忆跨会话持久化均正常。

### 3.4 RAG 知识库测试（8/8 通过）

| 编号 | 查询 | 预期关键词 | 命中 | 响应时间 | 结果 |
|------|------|-----------|------|----------|------|
| T-RAG-01 | "北京出差的住宿标准是多少？" | 500, 一线 | 500, 一线 | 19.3s | PASS |
| T-RAG-02 | "差旅费用应该在什么时候报销？" | 30, 天 | 30, 天 | 20.5s | PASS |
| T-RAG-03 | "机票应该提前多久预订比较好？" | 7, 14 | 7, 14 | 16.0s | PASS |
| T-RAG-04 | "出差可以携带家属吗？" | 不可以 | 不可以 | 19.2s | PASS |
| T-RAG-05 | "航班延误了应该怎么办？" | 改签, 凭证 | 改签, 凭证 | 30.9s | PASS |
| T-RAG-06 | "北京有哪些机场？" | 首都, 大兴 | 首都, 大兴 | 15.8s | PASS |
| T-RAG-07 | "阿里商旅平台有哪些功能？" | 申请, 预订 | 申请, 预订 | 26.6s | PASS |
| T-RAG-08 | "出差怎么做到环保？" | 高铁, 公共交通 | 高铁, 公共交通 | 37.8s | PASS |

**结论**: RAG 知识库问答准确率 100%，平均响应时间 23.3 秒，知识溯源正常。

### 3.5 信息查询测试（5/5 通过）

| 编号 | 查询 | 查询类型 | 成功 | 响应时间 | 结果 |
|------|------|----------|------|----------|------|
| T-INF-01 | "杭州的天气怎么样" | 天气查询 | 是 | 1.7s | PASS |
| T-INF-02 | "北京下周天气预报" | 天气查询 | 是 | 1.3s | PASS |
| T-INF-03 | "Claude AI 最新功能" | 网络搜索 | 是 | 21.9s | PASS |
| T-INF-04 | "Python async await 用法" | 网络搜索 | 是 | 32.6s | PASS |
| T-INF-05 | "什么是 RAG 检索增强生成" | 网络搜索 | 是 | 22.0s | PASS |

**结论**: 天气查询（wttr.in）和网络搜索（DuckDuckGo）均正常，天气查询响应快（~1.5s），搜索响应较慢（~25s）。

### 3.6 协调系统测试（2/2 通过）

| 编号 | 场景 | 意图识别 | 调度Agent数 | 执行状态 | 结果 |
|------|------|----------|-------------|----------|------|
| T-ORC-01 | "我要2月27日从上海去北京出差" | itinerary_planning | 2 (event_collection + itinerary_planning) | completed | PASS |
| T-ORC-02 | "北京的住宿标准是多少？" | rag_knowledge | 1 (rag_knowledge) | completed | PASS |

**结论**: 懒加载注册器发现 6 个技能插件，按优先级调度正常，LazyAgentRegistry 动态加载功能正常。

### 3.7 端到端 QA 测试（10/10 通过）

| 编号 | 问题 | 耗时 | 结果 |
|------|------|------|------|
| T-QA-01 | "出差住宿标准是多少？" | 72.4s | PASS |
| T-QA-02 | "如何报销差旅费用？需要哪些材料？" | 66.2s | PASS |
| T-QA-03 | "我从3月11日从北京出发，在杭州出差一周..." | 202.2s | PASS |
| T-QA-04 | "机票应该提前多久预订？有什么注意事项？" | 53.2s | PASS |
| T-QA-05 | "我偏好住万豪酒店和希尔顿，喜欢坐国航和东航..." | 64.7s | PASS |
| T-QA-06 | "杭州下周的天气怎么样？" | 45.9s | PASS |
| T-QA-07 | "从北京到深圳出差，住宿和交通标准分别是多少？" | 73.5s | PASS |
| T-QA-08 | "查询我最近的差旅记录" | 93.7s | PASS |
| T-QA-09 | "航班取消了怎么办？紧急情况联系谁？" | 92.7s | PASS |
| T-QA-10 | "我要去上海出差5天，帮我规划详细行程" | 186.5s | PASS |

**统计**: 10/10 成功，总耗时 951s，平均 95.1s/问题

**结论**: 端到端流程全部通过，覆盖全部 6 大意图场景。

---

## 4. 测试中发现的问题

### 4.1 已修复的问题

| 编号 | 问题 | 文件 | 修复方式 |
|------|------|------|----------|
| B-01 | `test_event_collection_agent.py` 使用 `sys.path.append('..')` 导致模块找不到 | tests/test_event_collection_agent.py | 改为绝对路径 |
| B-02 | `test_event_collection_agent.py` 未使用 async/await，返回 coroutine 对象 | tests/test_event_collection_agent.py | 改为异步函数 |
| B-03 | `test_orchestration.py` 导入已移至 skills 目录的 Agent 类 | tests/test_orchestration.py | 改用 LazyAgentRegistry |
| B-04 | `test_orchestration.py` 调用不存在的 `get_task_info()` 方法 | tests/test_orchestration.py | 改用 `get_full_context()` |
| B-05 | RAG Agent 中 `import json` 局部变量遮蔽模块级导入 | .claude/skills/ask-question/script/agent.py | 移除冗余 import |
| B-06 | Milvus collection 未 load 导致搜索失败 | .claude/skills/ask-question/script/agent.py | 搜索前调用 `load_collection()` |

### 4.2 已知残留问题

| 编号 | 问题 | 严重程度 | 说明 |
|------|------|----------|------|
| W-01 | ItineraryPlanningAgent 输出 JSON 解析偶尔失败 | 低 | LLM 输出的 JSON 中包含未转义的中文引号，json_parser 能捕获但降级处理 |
| W-02 | gRPC GOAWAY 警告 | 低 | Milvus Lite 的 gRPC keepalive 配置导致，不影响功能 |
| W-03 | AgentScope OpenAI 模型参数警告 | 低 | `temperature` 和 `max_tokens` 参数被忽略，不影响功能 |

---

## 5. 测试环境

- **OS**: Windows 11 Home China 10.0.26200
- **Python**: 3.x (系统安装)
- **AgentScope**: 1.0.16
- **pymilvus**: 2.6.9
- **LLM**: mimo-v2-pro (via token-plan-cn.xiaomimimo.com)
- **Embedding**: BGE-small-zh-v1.5 (本地部署)

---

## 6. 未覆盖模块

| 模块 | 说明 |
|------|------|
| 熔断器 (`utils/circuit_breaker.py`) | 无独立单元测试 |
| 重试退避 (`utils/llm_resilience.py`) | 无独立单元测试 |
| Web 服务 (`server/`) | FastAPI 路由无自动化测试 |
| Web 前端 (`web/`) | React 前端无测试 |
| PreferenceAgent | 通过端到端 QA 间接覆盖 |
| ItineraryPlanningAgent | 通过端到端 QA 间接覆盖 |

---

## 7. 改进建议

1. **引入 pytest 框架**: 将自定义脚本改为 pytest 用例，支持自动化断言和 CI 集成
2. **补充熔断器/重试测试**: 针对 `CircuitBreaker` 状态转换和 `retry_with_backoff` 编写独立测试
3. **LLM Mock**: 使用固定响应 mock LLM 调用，使测试可离线运行
4. **Web API 测试**: 为 FastAPI 路由编写 pytest + httpx 异步测试
5. **修复 JSON 解析**: ItineraryPlanningAgent 的 LLM 输出偶尔包含未转义字符，需优化 prompt

---

## 8. 结论

本次测试覆盖 **7 个测试文件、43 个测试用例**，**全部通过（100%）**。

测试中发现并修复了 6 个代码问题（导入路径、异步调用、变量遮蔽、Milvus 加载等），核心功能（意图识别、事项收集、记忆系统、RAG 知识库、信息查询、协调调度）均工作正常。

端到端 QA 测试验证了系统完整流程：从用户输入到意图识别、Agent 调度、结果聚合，全部 10 个场景成功通过。
