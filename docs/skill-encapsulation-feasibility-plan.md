# Aligo 旅行助手 → Claude Code Skill 封装可行性方案

## 一、项目现状分析

### 1.1 当前架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    用户界面层                             │
│   cli.py (Rich 终端)          web/ (React 19 + Vite)     │
└───────────────┬──────────────────┬──────────────────────┘
                │                  │
┌───────────────▼──────────────────▼──────────────────────┐
│                  Web 服务层                               │
│   server/app.py (FastAPI + SSE)                          │
│   server/session.py (LRU 会话缓存, 50个)                  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│               核心编排层                                  │
│   IntentionAgent (意图识别, LLM+正则在快速路由)           │
│        ↓                                                 │
│   OrchestrationAgent (优先级并行调度)                     │
│        ↓                                                 │
│   LazyAgentRegistry (12个Skill动态发现+懒加载)           │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              基础设施层                                   │
│   记忆系统 (ShortTermMemory + LongTermMemory)             │
│   缓存 (Redis / In-Process Dict)                         │
│   数据库 (PostgreSQL / JSON File)                        │
│   RAG (Milvus Lite + sentence-transformers)              │
│   熔断器 / 重试退避 / JSON 解析降级                       │
└─────────────────────────────────────────────────────────┘
```

### 1.2 核心数据流

```
用户输入 → IntentionAgent(意图识别, 缓存T=1800s)
         → 输出 JSON: {intents[], key_entities, agent_schedule[], fast_*} 
         → OrchestrationAgent(按优先级分组, 同优先级并行)
         → 各Skill Agent.reply() → JSON结果
         → 记忆更新 → 聚合响应
```

### 1.3 已经存在的12个 Skill 插件

| Skill 目录 | 功能 | 依赖 |
|---|---|---|
| ask-question | RAG知识库问答 | Milvus Lite, embedding模型 |
| currency-converter | 汇率查询 | frankfurter.app API |
| event-collection | 行程要素提取 | LLM |
| expense-tracker | 费用记录/查询 | LongTermMemory |
| hotel-search | 酒店/餐厅搜索 | 高德POI API |
| memory-query | 历史记忆查询 | LongTermMemory |
| plan-trip | 行程规划 | LLM + EventCollection结果 |
| preference | 偏好管理 | LongTermMemory |
| query-info | 天气/网络搜索 | 高德天气API + DDGS |
| train-ticket | 火车票查询 | 12306官方API |
| translation | 翻译 | MyMemory API |
| visa-info | 签证查询 | RAG (Milvus Lite) |

### 1.4 外部依赖复杂度

| 依赖 | 用途 | 是否可移植 |
|---|---|---|
| AgentScope 1.0.16 | Agent框架基类 | 核心依赖，可随skill打包 |
| OpenAIChatModel | LLM调用 | 可通过环境变量配置 |
| pymilvus[milvus_lite] | RAG向量库 | 可本地运行，但需下载embedding模型 |
| sentence-transformers | Embedding | 首次运行自动下载模型(~400MB) |
| PostgreSQL (asyncpg) | 可选存储 | JSON文件备选方案已就绪 |
| Redis | 可选缓存 | In-Process Dict备选已就绪 |
| FastAPI + uvicorn | Web服务 | 可选，skill模式不需要 |
| React + Vite | 前端 | 可选，skill模式不需要 |

---

## 二、"封装为 Skill.md" 的三种可行方案

### 方案A：Entry-Point Skill（推荐，低成本）

**思路**：创建一个顶层 `travel-assistant/SKILL.md` 作为整个系统的"入口技能"，通过调用CLI命令来驱动现有系统。

```
.claude/skills/travel-assistant/
├── SKILL.md                    # 技能定义 + 触发规则 + 调用指引
└── script/
    └── agent.py                # 薄包装层，复用现有 agents/ + context/
```

**优点**：
- 改动最小，1-2天可完成
- 100%复用现有代码，不破坏已有架构
- 12个现有子技能独立可用，可选是否全部纳入

**缺点**：
- 不能脱离当前项目目录运行
- 仍然依赖完整的Python环境
- 加载开销大（需初始化AgentScope、RAG等）

---

### 方案B：Self-Contained Skill（中等成本，高可移植性）

**思路**：将核心编排逻辑 + 所有Agent类 + 记忆系统 + 工具函数，全部内聚到单个skill目录中，成为一个自包含的"旅行助手引擎"。skill.md提供Claude Code的调用协议，script/下包含完整实现。

```
.claude/skills/travel-assistant/
├── SKILL.md                    # 技能元数据 + 用户指令
├── script/
│   ├── __init__.py
│   ├── agent.py                # 总入口：TravelAssistantSkill
│   ├── core/
│   │   ├── intention.py        # 意图识别（含快速路由正则）
│   │   ├── orchestrator.py     # 优先级并行调度
│   │   └── registry.py         # 子Agent注册与懒加载
│   ├── agents/                 # 12个子Agent（内联）
│   │   ├── expense_tracker.py
│   │   ├── currency_converter.py
│   │   ├── plan_trip.py
│   │   ├── ... (共12个)
│   ├── memory/
│   │   ├── short_term.py       # 滑动窗口内存
│   │   └── long_term.py        # JSON文件持久化
│   ├── utils/
│   │   ├── json_parser.py      # 健壮JSON解析
│   │   ├── skill_loader.py     # SKILL.md解析
│   │   └── circuit_breaker.py  # 熔断器
│   └── data/                   # 嵌入的知识数据
│       ├── knowledge_base/     # RAG文档（可选）
│       └── stations.json       # 火车站数据
└── requirements-skill.txt      # 精简依赖清单
```

**优点**：
- 作为一个独立技能，可在任意Claude Code项目中通过 `Skill` 工具调用
- 架构清晰，所有逻辑在一个目录下
- 可以进行依赖裁剪

**缺点**：
- 需要重构 ~5000行代码
- 12个Agent各依赖不同的外部API
- RAG部分需解决embedding模型的路径问题
- 工作量大（预估 5-10 天）

---

### 方案C：Headless API Skill（中等成本，最灵活）

**思路**：保持现有项目作为独立服务运行，skill.md只作为Claude Code与该服务之间的"代理层"，通过HTTP调用本地服务。

```
.claude/skills/travel-assistant/
├── SKILL.md                    # 触发规则 + API调用协议
└── script/
    └── agent.py                # HTTP Client，调用 localhost:8000/api/chat
```

**优点**：
- 前后端分离，skill极轻量
- 现有Web服务完全复用
- 可以通过SSE获得流式响应
- 改动最小

**缺点**：
- 需要后台运行 `python server/app.py`
- 网络调用增加延迟
- 不符合纯skill的"离线"语义

---

## 三、三种方案对比

| 维度 | 方案A Entry-Point | 方案B Self-Contained | 方案C Headless API |
|---|---|---|---|
| **开发工作量** | 1-2天 | 5-10天 | 1-2天 |
| **代码改动量** | ~200行新增 | ~3000行重构 | ~100行新增 |
| **可移植性** | 低（绑定项目目录） | 高（独立skill） | 中（需运行服务） |
| **依赖体积** | 完整 requirements.txt | 可裁剪到~8个核心依赖 | skill侧零依赖 |
| **LLM调用** | 通过AgentScope | 直接SDK调用 | 通过HTTP转发 |
| **RAG知识库** | 完整可用 | 需处理模型路径 | 完整可用 |
| **记忆系统** | 完整可用 | JSON模式可用 | 完整可用 |
| **响应延迟** | 2-5秒 | 2-5秒 | 3-6秒(+网络) |
| **维护性** | 好（不改原架构） | 中（两个版本需同步） | 好（不改原架构） |
| **Claude Code集成深度** | 浅（子进程调用） | 深（原生Python调用） | 中（HTTP调用） |

---

## 四、推荐方案：方案A（Entry-Point Skill）

### 推荐理由

1. **现有架构已经高度模块化** — 12个skill已经遵循 `SKILL.md + script/agent.py` 的格式
2. **不要重复造轮子** — IntentionAgent（150行正则+LLM提示）、OrchestrationAgent（优先级并行调度）、记忆系统都是成熟的
3. **Claude Code Skill 本质是"指令+脚本"** — 不需要剥离AgentScope，可以把它视为skill的依赖
4. **维护成本最低** — 不改动原有代码，只增加一个meta-skill做入口

### 架构设计

```
用户输入 (自然语言)
    │
    ▼
Claude Code Skill 工具调用
    │
    ▼
.claude/skills/travel-assistant/script/agent.py
    │
    ├─ 初始化 (复用 cli.py 的 initialize_system 逻辑)
    │   ├─ AgentScope.init
    │   ├─ OpenAIChatModel
    │   ├─ MemoryManager
    │   ├─ IntentionAgent
    │   ├─ LazyAgentRegistry (自动发现12个子技能)
    │   └─ OrchestrationAgent
    │
    ├─ process_query(user_input)
    │   ├─ IntentionAgent.reply()  → 意图识别
    │   └─ OrchestrationAgent.reply() → 子Agent调度
    │
    └─ 返回 JSON → Claude Code 呈现给用户
```

### SKILL.md 设计草案

```yaml
---
name: travel-assistant
description: >
  一站式智能旅行助手。支持：行程规划、费用记录、汇率查询、火车票查询、
  酒店搜索、翻译、签证政策、天气查询、企业差旅政策问答、偏好管理。
  Triggers when user asks about travel, trips, expenses, hotels, trains,
  flights, currency, translation, visa, or any travel-related questions.
---

## 功能矩阵

| 意图 | 触发示例 |
|------|---------|
| 行程规划 | "规划去北京3天", "从上海到杭州" |
| 费用记录 | "记一笔打车50元", "午餐花了80" |
| 汇率转换 | "100美元多少人民币", "日元汇率" |
| 火车票 | "查明天上海到北京的火车" |
| 酒店搜索 | "北京有哪些五星酒店" |
| 天气查询 | "北京明天天气" |
| 翻译 | "翻译成英文：你好" |
| 签证政策 | "去日本需要签证吗" |
| 差旅问答 | "住宿报销标准是多少" |
| 偏好管理 | "我喜欢住汉庭" |
| 记忆查询 | "我去过哪些地方" |
```

### agent.py 设计要点

```python
class TravelAssistantAgent(AgentBase):
    """
    总入口Agent，负责：
    1. 初始化系统（意图识别 + 编排器 + 所有子Agent）
    2. 接收用户输入
    3. 识别意图 → 调度子Agent → 聚合结果
    """

    async def reply(self, x):
        # 1. 意图识别
        intention_result = await self.intention_agent.reply(user_msg)

        # 2. 编排执行（并行/串行调度）
        orchestration_result = await self.orchestrator.reply(intention_result)

        # 3. 返回格式化结果
        return format_response(orchestration_result)
```

---

## 五、实施计划（方案A）

### 第一阶段：核心入口 Skill（1天）

#### Step 1: 创建 skill 目录结构

```
.claude/skills/travel-assistant/
├── SKILL.md
└── script/
    └── agent.py          ← 核心入口
```

#### Step 2: 实现 agent.py

- 复用 `cli.py` 中的 `initialize_system()` 逻辑
- 实现 `TravelAssistantEntryAgent.reply()`
- 处理意图识别 → 编排器调度 → 结果聚合

#### Step 3: 编写 SKILL.md

- 定义触发规则（旅行相关的所有关键词）
- 描述12个功能模块
- 提供使用示例

### 第二阶段：优化与测试（1天）

#### Step 4: 依赖精简

- 确认skill模式不需要的依赖（FastAPI、uvicorn、React）
- 编写 `requirements-skill.txt`（核心依赖子集）

#### Step 5: 集成测试

- 测试每个意图的端到端流程
- 测试快速路由（正则命中，不调LLM）
- 测试LLM降级路径

### 第三阶段：可选的深度优化

- 子Agent结果懒加载（首调用时才import对应agent.py）
- LLM调用结果缓存（加 `@cached` 装饰器）
- 记忆持久化路径调整（指向skill内的data/memory/）

---

## 六、关键风险与缓解措施

### 风险1：AgentScope 框架耦合

**影响**：方案B  
**缓解**：方案A和C都保留AgentScope，风险为0

### 风险2：Embedding模型下载

**影响**：RAG类技能（ask-question、visa-info）  
**缓解**：
- skill.md中注明首次使用需运行 `init_knowledge_base.py`
- 或使用 HF_ENDPOINT=https://hf-mirror.com 加速下载
- 或对于skill模式，提供轻量级BM25备选（不依赖embedding）

### 风险3：外部API不可用

**影响**：query-info（高德天气）、train-ticket（12306）、currency-converter（frankfurter）、hotel-search（高德POI）  
**缓解**：
- 每个API调用有超时设置（10-15秒）
- 返回明确的错误信息而非崩溃
- 可以考虑为关键API添加mock备选

### 风险4：Skill调用上下文限制

**影响**：Claude Code的skill调用有上下文窗口限制  
**缓解**：
- 结果自动截断（如行程规划的daily_plans最多显示3天摘要）
- 详细数据写入临时文件，skill返回文件路径
- 利用Claude Code的long-context能力（200K tokens）

---

## 七、建议与结论

### 最终推荐

**采用方案A（Entry-Point Skill）**，理由：

1. **现有12个skill已经半成品** — 每个都有 SKILL.md + agent.py
2. **项目核心价值在编排层** — IntentionAgent + OrchestrationAgent 才是"智能"的来源
3. **不要过度工程化** — 方案B的内聚重构roi低，且会导致维护两个版本
4. **Claude Code Skill 的定位是"指令+工具"** — 不是"独立应用"的替代品

### 工作量估算

| 阶段 | 内容 | 时间 |
|------|------|------|
| 创建 travel-assistant/SKILL.md | 编写触发规则、功能矩阵、使用指引 | 2小时 |
| 实现 script/agent.py | 复用现有初始化逻辑，包装为入口Agent | 4小时 |
| 编写 requirements-skill.txt | 精简依赖清单 | 1小时 |
| 集成测试 | 12个意图端到端验证 | 3小时 |
| 文档与优化 | 错误处理、边界情况 | 2小时 |
| **合计** | | **约1.5个工作日** |

### 长期演进路径

```
Phase 1 (当前方案A)
  travel-assistant/SKILL.md → 调用现有 agents/
  
Phase 2 (可选)
  将 script/agent.py 内联核心逻辑
  减少对 agents/ 的符号链接依赖
  
Phase 3 (可选)
  抽取为独立 pip 包: aligo-travel-assistant
  skill.md 只需 pip install + 配置API key
```
