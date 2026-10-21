# 回答后智能追问方案（完整版 v3）

## 目录

1. [主动反问（新功能）](#1-主动反问新功能)
2. [追问建议优化](#2-追问建议优化)
3. [实现计划](#3-实现计划)

---

## 1. 主动反问（新功能）

### 1.1 产品形态

每次大模型回答后，在回答卡片**下方**、追问建议**上方**，展示一条独立的主动反问：

```
┌─────────────────────────────────────────┐
│  [行程卡片 / 知识卡片 / 偏好卡片 / ...]   │  ← ResultDashboard（可导出）
├─────────────────────────────────────────┤
│                                         │
│  🤖 需要我帮你查一下青岛的机票和酒店吗？    │  ← 主动反问框（不可导出）
│                                         │
├ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
│  💡 你可能还想问                          │  ← 追问建议 chips
│  🚂 怎么去青岛  🌤️ 青岛天气  ...         │
└─────────────────────────────────────────┘
```

**与追问建议的本质区别**：

| | 主动反问 | 追问建议 |
|------|----------|----------|
| 数量 | **1 条** | 2-4 条 |
| 语气 | "需要我帮你...吗？" | 陈述式短标签 |
| 生成方式 | Agent 回复时附带 | 规则引擎 + LLM |
| 视觉 | 独立卡片框，有底色 | 圆角 chips |
| 导出行为 | **不导出** | 不导出 |

### 1.2 生成机制

#### 方案：Agent 在 reply 中附带 `proactive_question` 字段

每个 Skill Agent 的 `reply()` 返回的 JSON 中新增一个可选字段 `proactive_question`：

```json
{
  "status": "success",
  "answer": "出差住宿标准根据城市等级区分...",
  "proactive_question": "需要我帮你查一下具体某个城市的住宿标准吗？",
  "retrieved_documents": [...]
}
```

**生成策略**：在各 Agent 的 LLM prompt 中追加一句指令，让 LLM 同时生成反问：

```
在回答的最后，生成一句自然的主动反问（用"需要我帮你..."开头），
反问应基于当前对话自然衔接。如果当前对话已有明确结论或不需要追问，可以不生成。
反问控制在 25 字以内。
输出 JSON 时增加 "proactive_question" 字段。
```

**各 Agent 反问示例**：

| Agent | 用户输入 | 反问示例 |
|-------|---------|---------|
| preference | 我喜欢去青岛 | "需要我帮你规划一个去青岛的出差行程吗？" |
| rag_knowledge | 住宿标准是多少 | "需要我帮你查一下特定城市的住宿标准吗？" |
| expense_tracker | 记一笔午餐50元 | "需要我帮你看看这个月的费用汇总吗？" |
| itinerary_planning | 帮我规划去上海的行程 | "需要我帮你查一下上海未来几天的天气吗？" |
| information_query | 北京天气怎么样 | "需要我帮你查去北京的火车票吗？" |
| currency_converter | 100美元多少人民币 | "需要我帮你计算更大金额的汇率吗？" |

**降级策略**：
- 如果 Agent 没返回 `proactive_question` 或值为空 → 前端不显示反问框
- 如果多个 Agent 并行执行且都返回了反问 → 取优先级最高的 Agent 的反问
- 特殊场景（如 memory_query 查看历史、preference 删除操作）→ 可选择性不生成

#### 备选方案（如不想改 Agent prompt）：Orchestrator 统一生成

在 Orchestrator 收到所有 Agent 结果后，用一次轻量 LLM 调用统一生成反问：

```
上下文：用户说的是"{user_message}"，AI 执行了 {agent_names}，
回答摘要：{answer_summary}

生成一句自然的主动反问（用"需要我帮你..."开头），控制在 25 字以内。
只输出反问文本，不要 JSON 包装。
```

**方案对比**：

| | Agent 自行生成 | Orchestrator 统一生成 |
|------|---------------|---------------------|
| 响应延迟 | +0ms（一并输出） | +1-2s（多一次 LLM 调用） |
| 反问质量 | 贴近具体 Agent 语境 | 可综合多 Agent 结果 |
| 实现复杂度 | 改 8 个 Agent 的 prompt | 只改 Orchestrator 一处 |
| 推荐 | **推荐** | 备选 |

### 1.3 前端渲染

#### ProactiveQuestion 组件（新建）

```tsx
// web/src/components/Chat/ProactiveQuestion.tsx
function ProactiveQuestion({ question, onSend }: { question: string; onSend: (text: string) => void }) {
  if (!question) return null

  return (
    <div
      className="rounded-2xl px-4 py-3 cursor-pointer transition-all duration-200 hover:shadow-md active:scale-[0.98]"
      style={{
        backgroundColor: 'var(--accent-light)',
        border: '1.5px solid var(--accent)',
        borderStyle: 'dashed',
      }}
      onClick={() => onSend(question)}
    >
      <span className="text-[13px]" style={{ color: 'var(--accent)' }}>
        🤖 {question}
      </span>
      <span className="text-[11px] ml-2" style={{ color: 'var(--text-muted)' }}>
        点击直接提问
      </span>
    </div>
  )
}
```

#### 集成到 MessageBubble

在 `MessageBubble.tsx` 中，`ProactiveQuestion` 放在 `ResultDashboard` 和 `FollowUpSuggestions` 之间：

```
ResultDashboard     ← 可导出内容
ProactiveQuestion   ← 新增：不可导出
FollowUpSuggestions ← 已有：不可导出
```

### 1.4 导出隔离

这是用户特别关注的点：**规划卡片要支持导出，但不能把反问带进去**。

#### 实现方式

`ResultDashboard` 及其子卡片（`ItineraryCard`、`ExpenseCard` 等）是导出函数的数据源——导出时直接读取 `agentResults` 数组，逐个卡片提取文本，**只遍历 `ResultDashboard` 内的内容**。

`ProactiveQuestion` 和 `FollowUpSuggestions` 作为独立组件，不在 `agentResults` 中，导出函数天然不会触及。

导出逻辑示意：

```typescript
function exportToPDF(results: AgentResult[]) {
  let content = ''
  for (const r of results) {
    // 只提取 answer / itinerary / expense 等业务数据
    content += extractCardText(r)  // ← 不会包含 proactive_question
  }
  // ProactiveQuestion 和 FollowUpSuggestions 的数据虽然也在 results 的
  // data 字段中，但 extractCardText 按白名单提取，不会误采
}
```

**关键保证**：`proactive_question` 字段虽然在 agent 返回的 JSON 中，但前端的卡片渲染（`ItineraryCard`、`KnowledgeCard` 等）只读取 `answer` / `data` 等业务字段，不会渲染 `proactive_question`。导出函数同理。

---

## 2. 追问建议优化

### 2.1 问题回顾

当前追问建议存在"不识上下文"的问题：

| 用户输入 | 当前追问 | 期望追问 |
|---------|---------|---------|
| 我喜欢去青岛 | 查看偏好、出行偏好、删除偏好 | 怎么去青岛、青岛天气、青岛酒店价格、规划去青岛的行程 |

**根因**：`preference` 规则组只包含偏好管理类追问（查看/追加/删除），缺少跨技能衔接——用户提到一个城市名后，应自然衔接交通、天气、住宿。

### 2.2 优化一：从偏好值中提取城市名

在 `suggestionEngine.ts` 的 `extractExtras()` 函数中：

**当前**（preference case）：
```typescript
case 'preference': {
  // 只提取 pref_types
  if (Array.isArray(prefList) && prefList.length > 0) {
    extras.pref_types = prefList.map((p) => p.type)
    extras.pref_first_type = prefList[0].type
    extras.pref_first_value = prefList[0].value
  }
  break
}
```

**优化后**：
```typescript
case 'preference': {
  if (Array.isArray(prefList) && prefList.length > 0) {
    extras.pref_types = prefList.map((p) => p.type)
    extras.pref_first_type = prefList[0].type
    extras.pref_first_value = prefList[0].value
    // 新增：尝试从偏好值中提取城市名
    const city = extractCityName(String(prefList[0].value || ''))
    if (city && !extras.destination) {
      extras.destination = city
    }
  }
  break
}
```

### 2.3 优化二：新增城市名提取工具函数

```typescript
function extractCityName(text: string): string | null {
  // 中国主要城市直接匹配
  const CITY_LIST = [
    '北京', '上海', '广州', '深圳', '杭州', '南京', '成都', '武汉', '西安', '重庆',
    '青岛', '厦门', '大连', '天津', '苏州', '长沙', '郑州', '济南', '合肥', '福州',
    '南昌', '昆明', '贵阳', '南宁', '海口', '三亚', '拉萨', '乌鲁木齐', '哈尔滨',
    '长春', '沈阳', '太原', '石家庄', '兰州', '西宁', '银川', '呼和浩特', '桂林',
    '珠海', '东莞', '佛山', '无锡', '宁波', '温州', '常州',
  ]
  for (const city of CITY_LIST) {
    if (text.includes(city)) return city
  }
  // 正则兜底：去XX → 提取 XX
  const m = text.match(/去([一-龥]{2,4})(?:出差|旅游|玩|$)/)
  if (m) return m[1]
  return null
}
```

同时在 `extractExtras` 顶部增加一道通用提取（在现有正则基础上增强）：

```typescript
// 从用户消息中提取城市名（现有逻辑，增强正则覆盖面）
if (!extras.destination) {
  extras.destination = extractCityName(ctx.userMessage)
}
```

### 2.4 优化三：preference 规则组增强

在 `RULE_GROUPS.preference` 数组**最前面**插入跨技能规则（权重高于原规则）：

```typescript
preference: [
  // ── 新增：跨技能衔接（权重 112-120，高于偏好管理类）──
  {
    id: 'pref_cross_plan',      type: 'deepen',  icon: '🧳',
    text: '规划去{destination}的行程', query: '帮我规划去{destination}的出差行程',
    baseWeight: 120, condition: (c) => hasExtra(c.extras, 'destination'),
  },
  {
    id: 'pref_cross_train',     type: 'deepen',  icon: '🚂',
    text: '怎么去{destination}',        query: '查一下去{destination}的火车票',
    baseWeight: 118, condition: (c) => hasExtra(c.extras, 'destination'),
  },
  {
    id: 'pref_cross_weather',   type: 'explore', icon: '🌤️',
    text: '{destination}天气',          query: '{destination}天气怎么样',
    baseWeight: 115, condition: (c) => hasExtra(c.extras, 'destination'),
  },
  {
    id: 'pref_cross_hotel',     type: 'explore', icon: '🏨',
    text: '{destination}住宿价格',      query: '去{destination}住酒店大概要多少钱',
    baseWeight: 112, condition: (c) => hasExtra(c.extras, 'destination'),
  },
  {
    id: 'pref_cross_standard',  type: 'explore', icon: '💰',
    text: '{destination}住宿标准',      query: '{destination}出差住宿标准是多少',
    baseWeight: 108, condition: (c) => hasExtra(c.extras, 'destination'),
  },

  // ── 原有：偏好管理类（权重 55-110）──
  { id: 'pref_deepen_view', ... },  // 查看我的偏好 (110)
  { id: 'pref_deepen_hotel', ... }, // 酒店品牌偏好 (100)
  { id: 'pref_deepen_room', ... },  // 房型偏好 (95)
  { id: 'pref_explore_transport', ... }, // 出行偏好 (80)
  { id: 'pref_action_delete', ... },     // 删除偏好 (55)
],
```

**效果**：当 `extras.destination = "青岛"` 时，跨技能规则全部命中（权重 108-120），排序后它们占据前 4 位，原有的"查看偏好""删除偏好"自然被挤出。

### 2.5 优化四：matchPrefType 模糊匹配

当前只做精确匹配，偏好类型可能是 `travel_city` / `destination` / `city` 等多种变体：

```typescript
function matchPrefType(extras, type) {
  const types = extras.pref_types as string[] | undefined
  if (!types?.length) return false
  // 精确匹配
  if (types.includes(type)) return true
  // 别名匹配
  const aliases: Record<string, string[]> = {
    'destination': ['travel', 'city', 'destination', 'trip', 'place', 'travel_city'],
    'hotel': ['hotel', 'hotel_brand', 'accommodation', 'lodging'],
    'transport': ['transport', 'transit', 'car', 'flight', 'train', 'travel_mode'],
    'food': ['food', 'diet', 'meal', 'cuisine'],
    'airline': ['airline', 'flight', 'seat', 'air'],
  }
  return aliases[type]?.some(a => types.includes(a)) ?? false
}
```

### 2.6 优化五：LLM Prompt 增加跨意图指令

在 `llmSuggestions.ts` 的 prompt 中追加：

```
## 特别注意
- 如果用户表达了对某个城市的偏好（如"我喜欢去XX"），优先生成与该城市相关的追问：
  行程规划、交通方式、天气、住宿等，而不是偏好管理类问题
- 追问应自然衔接当前对话，不要跳到无关话题
- 口语化表达：用"怎么去青岛"而不是"查询青岛交通方式"
```

---

## 3. 实现计划

### 阶段一：主动反问（1 天）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 1 | Agent prompt 增加反问指令 | `agent.py` 等项目中的 Agent 文件 | 在 LLM prompt 中追加 1-2 句，要求输出 `proactive_question` 字段 |
| 2 | 后端 SSE 透传 `proactive_question` | `server/routes/chat.py` | 已透传 `data` 字段，无需改动 |
| 3 | 新建 `ProactiveQuestion.tsx` | `web/src/components/Chat/ProactiveQuestion.tsx` | 独立反问框组件（虚线边框、accent 底色） |
| 4 | 集成到 `MessageBubble.tsx` | 修改 ~5 行 | 插在 ResultDashboard 和 FollowUpSuggestions 之间 |
| 5 | 导出函数确保不包含反问 | 导出相关文件 | 遍历 `agentResults` 时按字段白名单提取 |

### 阶段二：追问建议优化（0.5 天）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6 | 新增 `extractCityName()` 函数 | `suggestionEngine.ts` | 城市列表 + 正则匹配 |
| 7 | `extractExtras` 增强 preference / 通用提取 | `suggestionEngine.ts` | 从偏好值和 userMessage 中提取城市名 |
| 8 | `matchPrefType` 模糊匹配 | `suggestionEngine.ts` | 别名映射 |
| 9 | preference 规则组增加跨技能规则 | `suggestionEngine.ts` | 5 条新规则，权重 108-120 |
| 10 | LLM prompt 增加跨意图指令 | `llmSuggestions.ts` | 追加 3 行指令 |

### 文件变更总览

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `web/src/components/Chat/ProactiveQuestion.tsx` | **新建** | ~35 |
| `web/src/components/Chat/MessageBubble.tsx` | 修改 | +8 |
| `web/src/api/suggestionEngine.ts` | 修改 | +55 |
| `web/src/api/llmSuggestions.ts` | 修改 | +5 |
| Agent `reply()` 方法（约 8 个 Agent） | 修改 prompt | 每个 +3 |
| 导出相关（前端） | 检查确认 | 0（天然隔离） |

**总计：1 个新文件，约 5 个修改，约 120 行，约 1.5 天。**

### 阶段一与阶段二可独立实施，互不阻塞。

---

## 附录 A：反问生成 Prompt 模板

各 Agent 的 prompt 中追加以下内容（以 RAG Agent 为例）：

```
在回答的最后，请生成一句主动的反问，用"需要我帮你..."开头，
基于用户当前问题自然延伸。例如：
- 用户问了住宿标准 → "需要我帮你查一下具体城市的住宿标准吗？"
- 用户问了报销流程 → "需要我帮你整理一份报销材料清单吗？"

要求：
1. 控制在 25 字以内
2. 如果当前回答已完全满足用户需求，可以留空
3. 反问要自然地衔接当前对话，不是推销功能

输出 JSON 时增加 "proactive_question" 字段（可为空字符串）。
```

## 附录 B：ProactiveQuestion 组件规格

```
样式：
- 圆角 16px (rounded-2xl)
- 虚线边框 1.5px dashed accent色
- 背景 accent色 8% 透明度
- 内边距 12px 16px
- 字号 13px
- 左侧 🤖 emoji

交互：
- 鼠标悬停 → 边框变实线，轻微阴影
- 点击 → 缩放反馈 (active: scale 0.98) + 发送反问文本
- 右侧有灰色小字"点击直接提问"

不显示条件：
- proactive_question 为空或 null
- 消息处于 streaming/loading 状态
- 当前消息是用户消息
```
