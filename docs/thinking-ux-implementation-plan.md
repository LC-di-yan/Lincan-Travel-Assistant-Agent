# 「旅行手记」Thinking UX 实现计划

## 目标

将 30-40 秒枯燥等待变成有叙事感的视觉体验。将当前静态的 `ThinkingIndicator`（"正在分析意图..." + 静态 SVG）替换为**迷你航线地图 + 打字机叙事时间线**。

后端零改动，纯前端。

---

## 架构总览

```
ChatPanel.tsx
├── [等待中] ThinkingJourney.tsx  ← 新建，替换 ThinkingIndicator
│   ├── FlightMap.tsx              ← 迷你航线地图 (SVG 动画)
│   ├── NarrativeTimeline.tsx      ← 叙事时间线 (打字机效果)
│   └── JourneyProgress.tsx        ← 进度条
│
├── [结果] StreamingPanel.tsx      ← 保留不动
└── [完成] ResultDashboard.tsx     ← 保留不动
```

### 数据流（SSE 事件 → 组件 props）

```
SSE event                              chatStore                           ThinkingJourney
─────────────────────────────────────────────────────────────────────────────────────────
thinking("analyzing_intent")    →     thinkingStatus                     → 地图节点0活跃
intention(data)                 →     currentIntention                   → 地图起点/终点 + 叙事第1行
                                       └─ rewritten_query
                                       └─ key_entities (origin/destination)
                                       └─ agent_schedule (完整清单)
agent_start(name)               →     addRunningAgent(name)              → 地图节点跳到对应位置
agent_result(data)              →     addAgentResult(data)               → 叙事第N行打字 + 地图节点亮绿
complete                       →     setProcessing(false)               → 完成动画 + 收起
```

### 关键洞察

- `intention` 事件在 SSE 流中**最早到达**（意图识别完成后），此时 `agent_schedule` 已包含完整 agent 清单
- 这意味着**总进度 = agent_schedule.length + 2**（意图 + 全部 agents + 整合），可以一开始就确定
- 地图不需要实时路线变化，只需要在节点间跳转

---

## 实施步骤

### Step 1: 状态准备 — chatStore 扩展 (微调)

**文件**: `web/src/store/chatStore.ts`

在现有 store 中增加 1 个字段（其他全部复用）：

```ts
// 已有 → 复用
thinkingStatus: string        // "analyzing_intent" | "executing_agents" | ""
currentIntention: IntentionData | null  // intention 事件的完整数据
currentAgents: AgentResult[]  // 已完成的 agent 结果
runningAgents: string[]       // 正在执行的 agent 名称列表

// 新增
thinkingPhase: number         // 0=意图, 1..N=agents, N+1=整合
```

改动量：1 个新字段 + 1 个 setter，约 6 行代码。

---

### Step 2: 核心组件 — ThinkingJourney.tsx (新建)

**文件**: `web/src/components/Chat/ThinkingJourney.tsx`

这是主容器组件，接收 store 状态并编排子组件。约 80 行。

```tsx
interface ThinkingJourneyProps {
  thinkingStatus: string
  intention: IntentionData | null
  agentResults: AgentResult[]
  runningAgents: string[]
}

export function ThinkingJourney({ thinkingStatus, intention, agentResults, runningAgents }: ThinkingJourneyProps) {
  // 阶段计算
  const phase = intention ? 1 : 0  // 0=意图识别中, 1+=agent执行中
  
  // 地图节点：从 agent_schedule 生成
  const nodes = useMemo(() => buildNodes(intention), [intention])
  
  // 当前活跃节点
  const activeNode = runningAgents.length > 0 ? runningAgents[runningAgents.length - 1] : null
  
  return (
    <div className="thinking-journey animate-fade-in-up">
      <FlightMap nodes={nodes} activeNode={activeNode} completedNodes={agentResults.map(r => r.agent_name)} />
      <NarrativeTimeline intention={intention} results={agentResults} running={runningAgents} />
      <JourneyProgress total={nodes.length} completed={agentResults.length + phase} />
    </div>
  )
}
```

#### 2a. 节点生成逻辑 `buildNodes()`

```ts
interface MapNode {
  id: string
  label: string
  icon: 'brain' | 'search' | 'train' | 'map' | 'calendar' | 'piggy' | 'default'
  color: string
  x: number   // SVG 坐标 (百分比)
  y: number
}

function buildNodes(intention: IntentionData | null): MapNode[] {
  const nodes: MapNode[] = [
    { id: 'intent', label: '理解需求', icon: 'brain', color: '#8b5cf6' }
  ]
  
  if (intention?.agent_schedule) {
    for (const agent of intention.agent_schedule) {
      nodes.push({
        id: agent.agent_name,
        label: getAgentLabel(agent.agent_name),
        icon: agentIconMap[agent.agent_name] || 'default',
        color: getAgentColor(agent.agent_name),
      })
    }
  }
  
  nodes.push({ id: 'complete', label: '整合结果', icon: 'map', color: '#10b981' })
  return nodes
}
```

---

### Step 3: 迷你航线地图 — FlightMap.tsx (新建)

**文件**: `web/src/components/Chat/FlightMap.tsx`

SVG 内联组件，约 120 行。

#### 视觉设计

```
  ●──────────✈️──────────●──────────●──────────○
理解需求    查询信息    生成行程   事项收集    整合结果
 (绿)       (蓝色脉冲)   (灰)       (灰)       (灰)
```

#### 技术方案

- **SVG Canvas**: `<svg viewBox="0 0 800 120" className="w-full h-auto">`
- **节点布局**: 等距水平排列，计算 `gap = 800 / (nodes.length + 1)`
- **节点圆**: `<circle cx={x} cy={60} r={14}>` 带颜色填充
- **连接线**: `<line x1={x1} y1={60} x2={x2} y2={60}>` 带 `stroke-dasharray` 动画
  - 已完成节点之间的线：实线、绿色
  - 当前节点之后的线：虚线、灰色
- **激活脉冲**: 当前活跃节点用 CSS `@keyframes pulse { 0% { r: 14; opacity: 1 } 100% { r: 24; opacity: 0 } }` 做波纹
- **完成动画**: 节点从灰变绿，`transition: fill 0.5s ease`

#### 状态驱动

| 节点状态 | 判定条件 | 视觉 |
|---------|---------|------|
| completed | `completedNodes.includes(node.id)` | 绿色实心 + 对勾 |
| active | `activeNode === node.id` | 蓝色 + pulse 动画 |
| pending | otherwise | 灰色空心 |

#### 坐标计算

```ts
const PADDING = 80
const Y_CENTER = 60
const nodePositions = nodes.map((_, i) => ({
  x: PADDING + (i / (nodes.length - 1)) * (800 - 2 * PADDING),
  y: Y_CENTER + (i % 2 === 0 ? -18 : 18)  // 锯齿排列增加动感
}))
```

---

### Step 4: 叙事时间线 — NarrativeTimeline.tsx (新建)

**文件**: `web/src/components/Chat/NarrativeTimeline.tsx`

打字机效果叙事列表，约 100 行。

#### 视觉设计

```
🧠 理解了：7月30日广州出发去揭阳出差3天
🚂 12306查到15趟列车，最快G3042次
📋 出发日期2026-07-30，目的地揭阳
⏳ 正在查询揭阳天气和注意事项...       ← 闪烁光标
```

#### 技术方案

- **滚动容器**: `max-h-48 overflow-y-auto`，新行自动 scrollToBottom
- **打字机效果**: 使用 `useEffect` + `setInterval`，每 30ms 显示一个字符
  ```ts
  function useTypewriter(text: string, enabled: boolean, speed = 30) {
    const [displayed, setDisplayed] = useState('')
    useEffect(() => {
      if (!enabled) { setDisplayed(text); return }
      let i = 0
      const timer = setInterval(() => {
        setDisplayed(text.slice(0, i + 1))
        i++
        if (i >= text.length) clearInterval(timer)
      }, speed)
      return () => clearInterval(timer)
    }, [text, enabled, speed])
    return displayed
  }
  ```
- **已完成行**: 直接显示全文（不打字），左侧绿色对勾
- **当前行**: 打字机逐字 + 闪烁光标 `|`（CSS `animation: blink 1s step-end infinite`）
- **等待行**: 灰色文字 + 旋转 spinner

#### 叙事文案模板

复用 `StreamingPanel.extractSummary()` 逻辑，扩展为更完整的叙事：

```ts
function buildNarrative(agentName: string, data: Record<string, unknown>): string {
  const d = (data?.data as Record<string, unknown>) || data || {}
  switch (agentName) {
    case 'event_collection': {
      const dest = d.destination || ''
      const date = d.date || d.start_date || ''
      return date && dest ? `${date} 出发前往 ${dest}` : `目的地: ${dest || '解析中...'}`
    }
    case 'preference': {
      const prefs = d.preferences as { value?: string }[] | undefined
      return Array.isArray(prefs) && prefs.length > 0
        ? `更新偏好: ${prefs.map(p => p.value).join('、')}`
        : '偏好已记录'
    }
    case 'information_query': {
      const results = d.results as Record<string, unknown> | undefined
      const summary = (results?.summary || d.summary || d.message) as string
      return summary ? `查询结果: ${summary.slice(0, 60)}` : '信息查询完成'
    }
    case 'itinerary_planning': {
      const itin = d.itinerary as Record<string, unknown> | undefined
      return `行程已生成: ${itin?.title || d.title || '查看详情'}`
    }
    case 'currency_converter': {
      return `汇率换算: ${d.from_amount} ${d.from_currency} = ${d.to_amount} ${d.to_currency}`
    }
    case 'expense_tracking': {
      return `费用已记录: ${d.category || ''} ${d.amount || ''}元`
    }
    default:
      return `${getAgentLabel(agentName)} 执行完成`
  }
}
```

---

### Step 5: 进度条 — JourneyProgress.tsx (新建)

**文件**: `web/src/components/Chat/JourneyProgress.tsx`

约 40 行，最简组件。

```tsx
function JourneyProgress({ total, completed }: { total: number; completed: number }) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0
  return (
    <div className="px-4 py-2">
      <div className="h-1.5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-600 ease-out"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, var(--accent), #10b981)',
          }}
        />
      </div>
      <p className="text-xs text-[var(--text-muted)] mt-1.5 text-right">{pct}%</p>
    </div>
  )
}
```

---

### Step 6: 集成 — 修改 ChatPanel.tsx

**文件**: `web/src/components/Chat/ChatPanel.tsx`（修改 1 行）

将第 211 行：
```tsx
{isProcessing && <ThinkingIndicator status={thinkingStatus} />}
```

替换为：
```tsx
{isProcessing && (
  <ThinkingJourney
    thinkingStatus={thinkingStatus}
    intention={currentIntention}
    agentResults={currentAgents}
    runningAgents={runningAgents}
  />
)}
```

需要从 store 中额外解构 `currentIntention`、`currentAgents`、`runningAgents`（已经在 store 中有对应的选择器）。

---

### Step 7: 完成动画

**文件**: `web/src/components/Chat/ThinkingJourney.tsx`（内置）

`complete` 事件到达 → `isProcessing` 变为 false → `ThinkingJourney` 不再渲染。

过渡效果：
1. CSS `@keyframes journey-exit`：opacity 0 + translateY(-20px)，300ms
2. 地图所有节点瞬间变绿（CSS transition）
3. `StreamingPanel` / `ResultDashboard` 从下方滑入

```css
.thinking-journey-exit {
  animation: journey-exit 0.4s ease forwards;
}
@keyframes journey-exit {
  to { opacity: 0; transform: translateY(-12px); max-height: 0; }
}
```

---

## 文件变更汇总

| 文件 | 操作 | 预计行数 |
|------|------|---------|
| `web/src/components/Chat/ThinkingJourney.tsx` | **新建** | ~80 |
| `web/src/components/Chat/FlightMap.tsx` | **新建** | ~120 |
| `web/src/components/Chat/NarrativeTimeline.tsx` | **新建** | ~100 |
| `web/src/components/Chat/JourneyProgress.tsx` | **新建** | ~40 |
| `web/src/components/Chat/ChatPanel.tsx` | **修改** 3 行 | +3 / -1 |
| `web/src/store/chatStore.ts` | **修改** 1 个字段 | +6 |

**总计: 4 个新文件 + 2 个微改，约 350 行新代码。**

---

## 边界情况处理

| 场景 | 处理 |
|------|------|
| 非行程查询（天气/知识问答） | 地图显示通用节点（agent 名），不依赖 origin/destination |
| Agent 执行失败 | 叙事行显示红色 ❌，地图节点变红，后续节点继续 |
| 特别快的 agent (< 1s) | 打字机速度提高到 15ms/字，仍能显示；或用 snap-to-end |
| 用户取消 | `abortActiveRequest()` 后 `isProcessing=false`，组件直接卸载 |
| 移动端窄屏 | SVG `viewBox` 自适应，叙事时间线字体缩小，地图节点间距压缩 |
| agent_schedule 为空 | 降级为 3 个固定节点（理解→执行→完成） |
| 意图识别阶段（节点 < 3 个） | 显示简化布局：单个脉冲节点 + "正在理解您的需求..." |

---

## 实施顺序

1. **Step 1** — chatStore 加字段（5 分钟）
2. **Step 5** — JourneyProgress 进度条（15 分钟，独立可测）
3. **Step 3** — FlightMap 地图（核心，2 小时）
4. **Step 4** — NarrativeTimeline 时间线（核心，1.5 小时）
5. **Step 2** — ThinkingJourney 容器（30 分钟，串起子组件）
6. **Step 6** — ChatPanel 集成（5 分钟）
7. **Step 7** — 完成动画 + 边界情况（1 小时）
8. 回归测试 + 实际触发一次完整对话流程（30 分钟）

**预计总时长：1 天。**
