# Aligo 前端 UI 美工优化方案

## 一、现状分析

当前 UI 功能完整，但视觉层次、空间节奏、动效细节、响应式适配均有提升空间。主要问题：

| 维度 | 现状 | 问题 |
|------|------|------|
| 视觉层次 | 所有卡片同质化 | 无主次之分，重点信息不突出 |
| 间距节奏 | 紧凑堆叠 | 留白不足，呼吸感差 |
| 动效 | 仅 pulse-dot | 缺少进入/退出动画、状态过渡 |
| 色彩 | 纯 CSS 变量 | 渐变、玻璃态、层次感不足 |
| 字体 | 系统默认 | 无字重对比，标题/正文区分弱 |
| 响应式 | 固定 72px 侧栏 | 小屏不可用，无折叠机制 |
| 暗色模式 | 基础反转 | 对比度不够，卡片缺少边界感 |

---

## 二、设计语言定义

### 2.1 设计关键词

**专业 · 温暖 · 通透**

- 专业：信息密度适中，层次分明
- 温暖：圆角、渐变、柔和阴影
- 通透：玻璃态、半透明、呼吸留白

### 2.2 色彩体系升级

```css
:root {
  /* 主色 — 保留蓝，增加品牌感 */
  --accent: #4f8ef7;
  --accent-hover: #3a7ae8;
  --accent-light: #e8f0fe;
  --accent-glow: rgba(79, 142, 247, 0.15);

  /* 中性色 — 增加层次 */
  --bg-primary: #ffffff;
  --bg-secondary: #f7f9fc;
  --bg-tertiary: #eef2f7;
  --bg-elevated: #ffffff;
  --bg-glass: rgba(255, 255, 255, 0.72);

  /* 阴影体系 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.08);
  --shadow-glow: 0 0 20px var(--accent-glow);
}

.dark {
  --bg-primary: #0c1222;
  --bg-secondary: #141c2e;
  --bg-tertiary: #1c2640;
  --bg-elevated: #1a2332;
  --bg-glass: rgba(12, 18, 34, 0.78);

  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.3);
  --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.4);
}
```

### 2.3 圆角规范

| 元素 | 圆角 |
|------|------|
| 卡片 | 16px |
| 气泡 | 20px（用户：右上 4px；助手：左上 4px） |
| 按钮 | 12px |
| 标签/徽章 | 999px（全圆） |
| 输入框 | 14px |

### 2.4 间距系统（4px 基准）

- 卡片内 padding：20px
- 卡片间距：16px
- 区块间距：24px
- 气泡内 padding：14px 18px

---

## 三、全局样式优化

### 3.1 globals.css 改造

```css
/* 渐变背景 — 替代纯色 */
body {
  background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
  min-height: 100vh;
}

/* 玻璃态通用类 */
.glass {
  background: var(--bg-glass);
  backdrop-filter: blur(16px) saturate(180%);
  -webkit-backdrop-filter: blur(16px) saturate(180%);
}

/* 卡片悬浮态 */
.card-hover {
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.card-hover:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

/* 进入动画 */
@keyframes fade-in-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.animate-fade-in-up {
  animation: fade-in-up 0.35s ease-out forwards;
}

/* 消息气泡进入 */
@keyframes bubble-in {
  from {
    opacity: 0;
    transform: scale(0.92) translateY(8px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}
.animate-bubble-in {
  animation: bubble-in 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}

/* 思考指示器升级 */
@keyframes thinking-wave {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
.thinking-wave span {
  animation: thinking-wave 1.2s ease-in-out infinite;
}
.thinking-wave span:nth-child(2) { animation-delay: 0.15s; }
.thinking-wave span:nth-child(3) { animation-delay: 0.3s; }

/* 渐变文字 */
.text-gradient {
  background: linear-gradient(135deg, var(--accent), #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* 骨架屏加载 */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
.skeleton {
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-secondary) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 8px;
}
```

### 3.2 滚动条美化

```css
::-webkit-scrollbar {
  width: 5px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--text-muted);
  border-radius: 999px;
  opacity: 0.4;
}
::-webkit-scrollbar-thumb:hover {
  opacity: 0.7;
}
```

---

## 四、组件级优化

### 4.1 Header — 玻璃态顶栏

**改动要点：**
- 背景改为玻璃态 `glass` 类
- 添加底部微光边框
- Logo 文字使用渐变色
- 添加 backdrop-filter 模糊效果

```tsx
<header className="h-14 flex items-center justify-between px-5 glass"
  style={{
    borderBottom: '1px solid var(--border)',
    backdropFilter: 'blur(16px) saturate(180%)',
  }}>
  <div className="flex items-center gap-2.5">
    <div className="w-8 h-8 rounded-xl flex items-center justify-center"
      style={{ background: 'linear-gradient(135deg, var(--accent), #8b5cf6)' }}>
      <Plane size={16} className="text-white" />
    </div>
    <span className="font-bold text-lg text-gradient">Aligo</span>
    <span className="text-xs text-[var(--text-muted)] font-medium tracking-wide">智能旅行助手</span>
  </div>
  {/* 右侧按钮组 — 增加间距和 hover 效果 */}
</header>
```

### 4.2 消息气泡 — 层次感提升

**用户气泡：**
- 添加微渐变背景
- 增加阴影
- 气泡尾部小三角

**助手气泡：**
- 使用 `bg-elevated` + 微阴影
- 头像改为渐变圆形 + 发光效果
- 添加进入动画 `animate-bubble-in`

```tsx
// 用户消息
<div className="inline-block px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm shadow-sm"
  style={{
    background: 'linear-gradient(135deg, var(--accent), #5a9cf7)',
    color: 'white',
    boxShadow: '0 2px 8px rgba(79, 142, 247, 0.25)',
  }}>
  {msg.content}
</div>

// 助手头像 — 发光
<div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
  style={{
    background: 'linear-gradient(135deg, var(--accent), #8b5cf6)',
    boxShadow: '0 0 12px var(--accent-glow)',
  }}>
  <Bot size={16} className="text-white" />
</div>
```

### 4.3 思考指示器 — 波浪动画

替换现有 pulse-dot 为更生动的波浪动画：

```tsx
export function ThinkingIndicator({ status }: { status: string }) {
  const labels: Record<string, string> = {
    analyzing_intent: '正在分析意图...',
    dispatching: '正在调度智能体...',
    '': '思考中...',
  }
  return (
    <div className="flex items-center gap-3 px-5 py-4 animate-fade-in-up">
      <div className="flex gap-1 thinking-wave">
        {[0, 1, 2].map((i) => (
          <span key={i} className="w-2 h-2 rounded-full"
            style={{ backgroundColor: 'var(--accent)' }} />
        ))}
      </div>
      <span className="text-sm text-[var(--text-muted)] font-medium">
        {labels[status] || status}
      </span>
    </div>
  )
}
```

### 4.4 结果卡片 — 统一卡片壳

所有结果卡片共享统一的卡片壳样式：

```tsx
// CardShell.tsx — 通用卡片容器
export function CardShell({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl overflow-hidden animate-fade-in-up ${className}`}
      style={{
        border: '1px solid var(--border)',
        backgroundColor: 'var(--bg-elevated)',
        boxShadow: 'var(--shadow-sm)',
      }}>
      {children}
    </div>
  )
}
```

**ItineraryCard 特殊处理：**
- 标题栏渐变增加紫色调
- 时间线节点增加脉冲动画
- 每日计划展开/折叠添加 `AnimatePresence` 过渡
- 活动卡片添加 hover 微抬起效果

### 4.5 InputBar — 输入区升级

- 外层容器使用玻璃态
- 输入框增加 placeholder 动画
- 发送按钮增加渐变 + glow 效果
- 添加字符计数提示（可选）

```tsx
<div className="border-t p-4 glass" style={{ borderColor: 'var(--border)' }}>
  <div className="flex items-end gap-3 max-w-4xl mx-auto">
    <textarea
      className="flex-1 resize-none rounded-2xl px-4 py-3 text-sm outline-none transition-all
        focus:ring-2 focus:ring-[var(--accent)] focus:shadow-[var(--shadow-glow)]
        disabled:opacity-50 placeholder:text-[var(--text-muted)]"
      style={{
        backgroundColor: 'var(--bg-primary)',
        color: 'var(--text-primary)',
        border: '1px solid var(--border)',
      }}
      placeholder="输入您的差旅需求..."
      // ...
    />
    <button
      className="p-3 rounded-2xl transition-all disabled:opacity-40
        hover:scale-105 active:scale-95"
      style={{
        background: 'linear-gradient(135deg, var(--accent), #8b5cf6)',
        color: 'white',
        boxShadow: '0 2px 8px rgba(79, 142, 247, 0.3)',
      }}>
      <Send size={18} />
    </button>
  </div>
</div>
```

### 4.6 Sidebar — 细节打磨

- Tab 指示器改为圆角胶囊样式（非底部线条）
- Tab 切换添加平滑过渡
- 空状态添加插图（SVG 或 emoji 组合）
- 面板切换添加淡入淡出

```tsx
// Tab 按钮 — 胶囊样式
<button
  className={`flex-1 flex items-center justify-center gap-1 py-2 text-xs font-medium
    rounded-lg mx-0.5 transition-all duration-200 ${
    tab === t.key
      ? 'text-[var(--accent)] shadow-sm'
      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
  }`}
  style={tab === t.key ? { backgroundColor: 'var(--accent-light)' } : {}}
>
  <t.icon size={12} />
  {t.label}
</button>
```

### 4.7 IntentPanel — 可视化增强

- 意图置信度进度条增加渐变色
- Agent 状态节点增加连线
- 推理过程添加代码块样式
- 实体标签增加图标前缀

```tsx
// 进度条渐变
<div className="h-full rounded-full transition-all duration-500"
  style={{
    width: `${intent.confidence * 100}%`,
    background: intent.confidence > 0.7
      ? 'linear-gradient(90deg, var(--success), #34d399)'
      : 'linear-gradient(90deg, var(--warning), #fbbf24)',
  }} />
```

### 4.8 ThemeToggle — 过渡动画

```tsx
export function ThemeToggle({ dark, toggle }: { dark: boolean; toggle: () => void }) {
  return (
    <button onClick={toggle}
      className="p-2 rounded-xl transition-all duration-300 hover:bg-[var(--bg-tertiary)] hover:scale-110 active:scale-95"
      title={dark ? '切换亮色' : '切换暗色'}>
      <div className="relative w-[18px] h-[18px]">
        <Sun size={18}
          className={`absolute inset-0 text-[var(--warning)] transition-all duration-300 ${
            dark ? 'opacity-100 rotate-0' : 'opacity-0 -rotate-90'
          }`} />
        <Moon size={18}
          className={`absolute inset-0 text-[var(--text-secondary)] transition-all duration-300 ${
            dark ? 'opacity-0 rotate-90' : 'opacity-100 rotate-0'
          }`} />
      </div>
    </button>
  )
}
```

---

## 五、布局优化

### 5.1 响应式侧栏

```tsx
// App.tsx — 侧栏可折叠
export default function App() {
  const { dark, toggle } = useTheme()
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="h-screen flex flex-col" style={{ backgroundColor: 'var(--bg-primary)' }}>
      <Header dark={dark} toggle={toggle} onToggleSidebar={() => setSidebarOpen(v => !v)} />
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col min-w-0">
          <ChatPanel />
        </div>
        {/* 侧栏 — 带滑入动画 */}
        <div className={`border-l flex-shrink-0 overflow-hidden transition-all duration-300 ${
          sidebarOpen ? 'w-72' : 'w-0'
        }`} style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-primary)' }}>
          <div className="w-72 h-full">
            <Sidebar />
          </div>
        </div>
      </div>
    </div>
  )
}
```

### 5.2 空状态升级

欢迎页面增加视觉吸引力：

```tsx
<div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)]">
  {/* 渐变背景圆 */}
  <div className="relative mb-6">
    <div className="w-20 h-20 rounded-full flex items-center justify-center"
      style={{
        background: 'linear-gradient(135deg, var(--accent-light), rgba(139, 92, 246, 0.1))',
        boxShadow: 'var(--shadow-glow)',
      }}>
      <span className="text-4xl">🌏</span>
    </div>
  </div>
  <p className="text-xl font-bold text-gradient mb-2">Aligo 智能旅行助手</p>
  <p className="text-sm text-[var(--text-muted)] max-w-sm text-center leading-relaxed">
    告诉我您的差旅需求，我会为您规划行程、查询信息、管理偏好
  </p>
  {/* 推荐问题 — 卡片化 */}
  <div className="mt-8 grid grid-cols-2 gap-2 max-w-md">
    {['明天从北京去上海出差3天', '出差住宿标准是多少？', '北京天气怎么样？', '我住酒店喜欢汉庭'].map((q) => (
      <button key={q}
        onClick={() => handleSend(q)}
        className="text-xs px-4 py-3 rounded-xl transition-all card-hover text-left"
        style={{
          border: '1px solid var(--border)',
          backgroundColor: 'var(--bg-elevated)',
          color: 'var(--text-secondary)',
          boxShadow: 'var(--shadow-sm)',
        }}>
        {q}
      </button>
    ))}
  </div>
</div>
```

---

## 六、暗色模式精调

### 6.1 对比度增强

当前暗色模式问题：卡片与背景融合度太高，边界感弱。

**解决：**
- 暗色下增加卡片边框亮度：`--border: #3d4a63`
- 暗色下增加阴影深度
- 暗色下 accent 色增加饱和度

### 6.2 暗色专用渐变

```css
.dark .text-gradient {
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
}

.dark .card-hover:hover {
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(96, 165, 250, 0.1);
}
```

---

## 七、动效清单

| 元素 | 动效 | 时长 | 缓动 |
|------|------|------|------|
| 消息气泡进入 | scale + fade + translateY | 300ms | cubic-bezier(0.34, 1.56, 0.64, 1) |
| 结果卡片进入 | fade + translateY | 350ms | ease-out |
| 思考指示器 | 波浪位移 | 1200ms | ease-in-out |
| 主题切换 | 颜色过渡 | 300ms | ease |
| 侧栏展开/收起 | width | 300ms | ease-in-out |
| 按钮 hover | scale(1.05) | 150ms | ease |
| 按钮 active | scale(0.95) | 100ms | ease |
| Tab 切换 | 背景色 + 文字色 | 200ms | ease |
| 进度条填充 | width | 500ms | ease-out |
| 头像发光 | box-shadow pulse | 2000ms | ease-in-out |

---

## 八、实施优先级

| 优先级 | 内容 | 预估工时 |
|--------|------|----------|
| P0 | 色彩体系 + CSS 变量 + 全局样式 | 1h |
| P0 | 玻璃态 Header + 气泡升级 | 1h |
| P0 | 思考指示器 + 进入动画 | 0.5h |
| P1 | 结果卡片壳统一 + ItineraryCard 渐变 | 1h |
| P1 | InputBar 升级 + 发送按钮渐变 | 0.5h |
| P1 | Sidebar Tab 胶囊 + 空状态美化 | 0.5h |
| P2 | 响应式侧栏折叠 | 1h |
| P2 | 暗色模式精调 | 0.5h |
| P2 | ThemeToggle 过渡动画 | 0.5h |
| P3 | 骨架屏加载态 | 1h |
| P3 | 消息列表虚拟滚动 | 2h |

---

## 九、依赖引入

```bash
# 仅需 tailwindcss（已有），无需额外依赖
# 如需 AnimatePresence 可加 framer-motion（可选）
npm install framer-motion   # 可选，用于复杂布局动画
```

---

## 十、效果预览对比

### 改版前
```
┌─────────────────────────────────────────────────┐
│ ✈ Aligo  智能旅行助手          [user] [🗑] [🌙] │ ← 纯色背景，无层次
├──────────────────────────────────┬──────────────┤
│                                  │ 意图 偏好 历史│
│  🌏                              │              │
│  Aligo 智能旅行助手              │  识别意图     │
│  输入您的差旅需求                │  行程规划 85% │
│                                  │              │
│  [明天从北京去上海] [天气]       │  关键信息     │
│                                  │  北京 上海    │
│                                  │              │
├──────────────────────────────────┤              │
│ [输入您的需求...            ] [→]│              │
└──────────────────────────────────┴──────────────┘
```

### 改版后
```
┌─────────────────────────────────────────────────┐
│ ✈ Aligo  智能旅行助手          [user] [🗑] [☀️] │ ← 玻璃态，模糊背景
├──────────────────────────────────┬──────────────┤
│                                  │ [意图] 偏好 历史│ ← 胶囊 Tab
│    ╭─────────────╮               │              │
│    │  🌏         │               │  ◆ 识别意图  │
│    ╰─────────────╯               │  行程规划    │
│                                  │  ████████░ 85%│ ← 渐变进度条
│  Aligo 智能旅行助手              │              │
│  告诉我您的差旅需求...           │  ◇ 关键信息  │
│                                  │  📍北京→上海 │ ← 图标标签
│  ┌──────────┐ ┌──────────┐      │              │
│  │明天从北京 │ │出差住宿  │      │  ⚡ 调度计划 │
│  │去上海出差 │ │标准是多少│      │  ● 行程规划  │
│  └──────────┘ └──────────┘      │  ○ 偏好管理  │
│                                  │              │
├──────────────────────────────────┤              │
│ ╭────────────────────────────╮ ┌─┤              │
│ │ 输入您的差旅需求...        │ │→│              │ ← 渐变按钮
│ ╰────────────────────────────╯ └─┤              │
└──────────────────────────────────┴──────────────┘
  ↑ 圆角卡片 + 阴影          ↑ 卡片 hover 浮起
```
