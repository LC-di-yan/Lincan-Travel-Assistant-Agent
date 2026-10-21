# Aligo 商旅 Skills（Claude / Cursor 可用）

基于本项目 **agents/** 实际实现的业务 Skills，便于在 Claude 或 Cursor 中按意图调用对应 Agent。

---

## 怎么用、怎么问 Claude

在对话里**用自然语言说出你的需求**，Claude 会根据描述自动选用对应的 Skill（或组合多个）。不需要记命令，直接像和同事说话一样问即可。

下面按 Skill 列出**典型问法**和**会得到什么**。

---

### 1. ask-question（知识库问答）

**怎么问：**
- 「北京的住宿标准是多少？」
- 「差旅费用什么时候报销？流程是啥？」
- 「航班延误了怎么办？」
- 「如何改签/退票？」
- 「上海差旅有什么注意事项？」

**会干啥：** 用 RAG 从项目知识库（`data/documents/`）检索文档，用 LLM 生成答案，并给出参考来源。  
**前置条件：** 已运行过 `python scripts/init_knowledge_base.py`。

---

### 2. query-info（天气 / 网络搜索）

**怎么问：**
- 「北京明天天气怎么样？」
- 「上海下周天气」
- 「查一下 XX 景点开放时间」
- 「搜一下最近 XX 新闻」

**会干啥：** 天气走 wttr.in；其他用 DDGS 做网络搜索并给摘要。  
**注意：** 差旅标准、报销政策这类请用「知识库问答」问，不要用「查一下差旅标准」当搜索。

---

### 3. plan-trip（行程规划）

**怎么问：**
- 「帮我规划一下从上海到北京的行程」
- 「2 月 27 日去北京出差，帮我安排一下」
- 「我想去杭州玩两天，怎么安排？」
- 「从广州到成都，3 天，规划路线」

**会干啥：** 先做意图识别，再收集出发地、目的地、日期等，最后生成行程（每日安排、交通、住宿建议等）。  
**可能被追问：** 缺出发地、日期等信息时，Claude 会问你补全。

---

### 4. memory-query（查我的历史）

**怎么问：**
- 「我去过哪些地方？」
- 「我上次去北京是什么时候？」
- 「我之前说过什么偏好？」
- 「我的旅行记录有哪些？」

**会干啥：** 从长期记忆（`data/memory/{user_id}.json`）里查你的行程、偏好、对话摘要，用自然语言回答。  
**前置条件：** 需要有 MemoryManager（user_id/session_id），且之前有用过 CLI 或其它方式写入过记忆。

---

### 5. preference（保存 / 改我的偏好）

**怎么问：**
- 「我喜欢住汉庭」
- 「我还喜欢如家」（追加酒店偏好）
- 「我常坐东航」（追加航空公司）
- 「我搬家到上海浦东了」（覆盖常住地）
- 「改成靠窗座位」（覆盖座位偏好）

**会干啥：** 识别是「追加」还是「覆盖」，把偏好写入长期记忆；后续规划、记忆查询都会用到。  
**前置条件：** 同 memory-query，需要 MemoryManager。

---

### 组合问法（一次多件事）

也可以一句话里带多个意图，例如：
- 「我想去北京出差，先帮我查一下北京天气，再按差标说说住宿标准。」  
Claude 会依次用 **query-info**（天气）和 **ask-question**（住宿标准）。

### 6. expense-tracker（费用记录）

**怎么问：**
- 「记一笔打车费50元」
- 「午餐花了80」
- 「这次出差花了多少钱」
- 「差旅费用汇总」

**会干啥：** 用 LLM 解析自然语言费用描述，自动分类（交通/餐饮/住宿等），写入长期记忆。支持按时间范围汇总。

---

### 7. currency-converter（汇率换算）

**怎么问：**
- 「100美元多少人民币」
- 「日元汇率」
- 「美元兑欧元」
- 「500英镑换成人民币」

**会干啥：** 调用 frankfurter.app API 获取实时汇率，支持 CNY/USD/EUR/JPY/GBP/KRW/SGD 等 12 种货币。

---

### 8. translation（翻译）

**怎么问：**
- 「翻译成英文」
- 「用日语怎么说你好」
- 「translate to Chinese」
- 「帮我翻译这段话」

**会干啥：** 调用 MyMemory API 进行多语言翻译，支持中英日韩法德西等 11+ 种语言。

---

### 9. visa-info（签证信息）

**怎么问：**
- 「去日本需要签证吗」
- 「泰国签证怎么办」
- 「去美国需要什么材料」
- 「免签国家有哪些」

**会干啥：** 通过 RAG 检索签证知识文档，返回签证政策、所需材料、办理流程等信息。

---

## 可用 Skills 一览

| Skill | 用途 | 触发示例 | 主要 Agent |
|-------|------|----------|------------|
| **ask-question** | 差旅政策/报销/预订/城市指南等知识问答 | 「XX标准是多少」「如何报销」「航班延误怎么办」 | RAGKnowledgeAgent |
| **query-info** | 天气、网络搜索等实时信息 | 「天气怎么样」「查一下XX」 | InformationQueryAgent |
| **plan-trip** | 行程规划 | 「规划行程」「从XX到XX」「X月X日去北京」 | IntentionAgent → EventCollectionAgent → ItineraryPlanningAgent |
| **memory-query** | 查询用户自己的历史行程与偏好 | 「我去过哪些地方」「我上次去北京是什么时候」 | MemoryQueryAgent |
| **preference** | 保存/追加/覆盖用户偏好 | 「我喜欢住汉庭」「我还喜欢如家」「我搬家到上海了」 | PreferenceAgent |
| **expense-tracker** | 记录、查询、汇总差旅费用 | 「记一笔打车费50元」「这次出差花了多少钱」 | ExpenseTrackerAgent |
| **currency-converter** | 实时汇率查询与货币换算 | 「100美元多少人民币」「日元汇率」 | CurrencyConverterAgent |
| **translation** | 多语言翻译 | 「翻译成英文」「用日语怎么说」 | TranslationAgent |
| **visa-info** | 签证政策与入境要求查询 | 「去日本需要签证吗」「泰国签证怎么办」 | VisaInfoAgent |

---

## 统一约定（与代码一致）

1. **模型传入方式**  
   所有 Agent 使用 **`model=model`**（传入已创建的 `OpenAIChatModel` 实例）。  
   本项目**没有** `model_config_name` 参数。

2. **异步调用**  
   所有子 Agent 的 `reply()` 均为 **async**，调用时需 **await**。

3. **模型创建**  
   ```python
   from agentscope.model import OpenAIChatModel
   from config import LLM_CONFIG
   model = OpenAIChatModel(
       model_name=LLM_CONFIG["model_name"],
       api_key=LLM_CONFIG["api_key"],
       client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
       temperature=LLM_CONFIG.get("temperature", 0.7),
       max_tokens=LLM_CONFIG.get("max_tokens", 2000),
   )
   ```

4. **依赖 main.py / cli.py**  
   Skills 直接导入 **agents/** 与 **context/**，不依赖 `main.py` 或 `cli.py`。完整交互流程见 `cli.py`。

---

## Agent 与文件对应

| Agent | 文件 | 职责 |
|-------|------|------|
| IntentionAgent | agents/intention_agent.py | 意图识别与智能体调度 |
| OrchestrationAgent | agents/orchestration_agent.py | 协调多 Agent |
| EventCollectionAgent | .claude/skills/event-collection/script/agent.py | 出发地、目的地、日期等事项收集 |
| PreferenceAgent | .claude/skills/preference/script/agent.py | 用户偏好识别（追加/覆盖） |
| InformationQueryAgent | .claude/skills/query-info/script/agent.py | 天气、网络搜索 |
| RAGKnowledgeAgent | .claude/skills/ask-question/script/agent.py | 知识库检索与问答 |
| MemoryQueryAgent | .claude/skills/memory-query/script/agent.py | 基于长期记忆回答历史问题 |
| ItineraryPlanningAgent | .claude/skills/plan-trip/script/agent.py | 生成行程计划 |
| ExpenseTrackerAgent | .claude/skills/expense-tracker/script/agent.py | 费用记录与汇总 |
| CurrencyConverterAgent | .claude/skills/currency-converter/script/agent.py | 汇率查询与换算 |
| TranslationAgent | .claude/skills/translation/script/agent.py | 多语言翻译 |
| VisaInfoAgent | .claude/skills/visa-info/script/agent.py | 签证政策查询 |

---

## 目录结构

```
.claude/skills/
├── README.md
├── ask-question/           # 知识库问答 (RAG)
├── query-info/             # 天气/网络搜索
├── plan-trip/              # 行程规划
├── memory-query/           # 记忆查询
├── preference/             # 偏好管理
├── event-collection/       # 事项收集
├── expense-tracker/        # 费用记录
├── currency-converter/     # 汇率换算
├── translation/            # 翻译
└── visa-info/              # 签证信息
```

---
