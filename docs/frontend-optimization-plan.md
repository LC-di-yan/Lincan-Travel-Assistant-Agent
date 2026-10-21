# Aligo 智能旅行助手 - 前端视觉优化方案

## 一、现状分析

### 当前技术栈
- **框架**: React 19 + TypeScript + Vite 8
- **样式**: Tailwind CSS 4 + CSS Variables (自定义 design tokens)
- **状态管理**: Zustand
- **图标**: Lucide React + 自定义 SVG
- **Markdown**: react-markdown

### 现有资源
| 路径 | 内容 | 状态 |
|------|------|------|
| `public/images/illustrations/empty-state.svg` | 地球+飞机+城市的矢量插画 | 已有，质量较好 |
| `public/images/illustrations/error.svg` | 破齿轮+感叹号 | 已有，较简陋 |
| `public/images/icons/agent-*.svg` (8个) | 各 Agent 的标识图标 | 已有，风格统一 |
| `public/images/icons/logo.svg` | Logo | 已有 |
| `public/images/patterns/grid-pattern.svg` | 网格点阵背景 | 已有，已用于 body::before |
| `public/images/patterns/wave-pattern.svg` | 波浪纹理 | 已有，未使用 |

### 当前不足
1. **空状态单一**: 只有一个 empty-state 插画，缺少暗色模式适配
2. **结果卡片缺乏视觉层次**: 行程卡片、事件卡片等只有文字+图标，没有配图
3. **思考状态过于简单**: 只有三个跳动的圆点，缺少品牌感
4. **侧边栏空状态简陋**: 各 Tab 的空状态只有一个小图标+文字
5. **欢迎页不够吸引人**: 缺少 Hero 级别的视觉冲击
6. **城市/场景图片缺失**: 行程规划结果没有目的地视觉元素
7. **费用/汇率卡片没有图形化**: 数据展示纯文字，缺少图表或图形化
8. **暗色模式下部分插画不可见**: SVG 的 fill/stroke 硬编码了颜色

---

## 二、优化方案总览

### 核心策略
> **自建 SVG 插画库 + CSS 动态主题适配 + 数据可视化增强**

不引入外部图片依赖，全部使用高质量 SVG 矢量图（可内联或外链），配合 CSS 变量实现亮/暗模式自动切换。

### 资源目录结构
```
web/public/images/
├── illustrations/          # 大尺寸插画（空状态、欢迎页等）
│   ├── empty-state.svg     # [已有] 空聊天状态
│   ├── empty-state-dark.svg # [新增] 暗色模式空状态
│   ├── welcome-hero.svg    # [新增] 欢迎页 Hero 插画
│   ├── error.svg           # [优化] 错误状态
│   ├── thinking.svg        # [新增] 思考中的品牌插画
│   ├── trip-success.svg    # [新增] 行程规划成功
│   ├── no-history.svg      # [新增] 无历史记录
│   └── no-preference.svg   # [新增] 无偏好设置
├── cities/                 # [新增] 城市剪影/地标
│   ├── beijing.svg         # 北京（天坛/故宫轮廓）
│   ├── shanghai.svg        # 上海（东方明珠轮廓）
│   ├── guangzhou.svg       # 广州（小蛮腰轮廓）
│   ├── shenzhen.svg        # 深圳（地王大厦轮廓）
│   ├── chengdu.svg         # 成都（熊猫轮廓）
│   ├── hangzhou.svg        # 杭州（雷峰塔轮廓）
│   └── default-city.svg    # 通用城市轮廓
├── scenes/                 # [新增] 场景插画
│   ├── flight.svg          # 飞行场景
│   ├── hotel.svg           # 酒店场景
│   ├── meeting.svg         # 会议场景
│   ├── dining.svg          # 餐饮场景
│   └── transport.svg       # 交通场景
├── icons/                  # [已有] Agent 图标
│   └── ... (保持现有)
├── patterns/               # [已有] 背景纹理
│   ├── grid-pattern.svg    # [已有]
│   └── wave-pattern.svg    # [已有]
└── badges/                 # [新增] 状态徽章
    ├── premium.svg
    └── verified.svg
```

---

## 三、分模块优化细节

### 3.1 欢迎页 (ChatPanel 空状态)

**现状**: 一个 SVG 插画 + 标题 + 3 个功能卡片 + 2 个快捷按钮

**优化方案**:
- 新增一个更大的 Hero 插画 `welcome-hero.svg`，包含：飞机航线 + 地球 + 城市天际线 + 云朵，带浮动动画
- 插画支持暗色模式：使用 CSS `currentColor` 或 `var()` 引用，使 SVG 自动适配主题
- 功能卡片增加微交互：hover 时卡片内的小图标播放一次动画
- 新增 4-6 个快捷提问（从 2 个扩展），按类别分组：「行程」「查询」「偏好」

**效果预览**:
```
┌──────────────────────────────────────────────┐
│                                              │
│           [ Hero 插画 - 浮动动画 ]            │
│          飞机绕地球飞行 + 城市天际线            │
│                                              │
│         ✨ Aligo 智能旅行助手 ✨               │
│      告诉我您的差旅需求，我来帮您规划           │
│                                              │
│   ┌──────┐  ┌──────┐  ┌──────┐              │
│   │ 行程 │  │ 知识 │  │ 偏好 │              │
│   │ 规划 │  │ 查询 │  │ 管理 │              │
│   └──────┘  └──────┘  └──────┘              │
│                                              │
│  [北京天气] [出差标准] [上次去哪了] [汇率查询]  │
└──────────────────────────────────────────────┘
```

### 3.2 行程卡片 (ItineraryCard)

**现状**: 紫色渐变头部 + 时间线列表 + 注意事项

**优化方案**:
- 根据目的地城市自动匹配城市剪影 SVG 作为卡片背景装饰（右下角半透明叠加）
- 时间线节点增加图标：交通用高铁/飞机 SVG，景点用建筑 SVG，餐饮用餐具 SVG（替代 emoji）
- 注意事项区域增加一个「旅行小贴士」图标
- 卡片顶部增加一个路线概览条：出发地 → 目的地 的简化路线图

**新增组件**: `CityIllustration` - 根据城市名返回对应 SVG

### 3.3 事件卡片 (EventCard)

**现状**: 2x2 网格显示出发地/目的地/日期/目的

**优化方案**:
- 卡片顶部增加「出发地 → 目的地」的路线可视化（两个定位图标 + 连接虚线）
- 根据 trip_purpose 显示对应场景插画（会议→meeting.svg，出差→flight.svg）
- 缺少信息的警告增加更明显的视觉提示

### 3.4 信息卡片 (InfoCard)

**现状**: 天气/搜索结果纯文字

**优化方案**:
- **天气卡片**: 根据天气状况显示对应 SVG 图标（晴天/多云/雨天/雪天），温度用大字体突出显示
- **搜索结果**: 增加搜索来源的 favicon 或品牌色标识

**新增组件**: `WeatherIcon` - 根据天气描述返回对应 SVG

### 3.5 思考指示器 (ThinkingIndicator)

**现状**: 三个跳动圆点 + 状态文字

**优化方案**:
- 替换为品牌化的思考动画：一个小型飞机沿着弧线飞行的 SVG 动画
- 不同状态显示不同的动画阶段：
  - `analyzing_intent`: 飞机起飞
  - `dispatching`: 飞机巡航
  - 默认思考: 飞机盘旋

### 3.6 侧边栏空状态

**现状**: 各 Tab 空状态只有一个小 Lucide 图标

**优化方案**:
- 意图面板空状态: 显示一个「雷达扫描」SVG 动画
- 偏好面板空状态: 显示一个「空行李箱」SVG 插画
- 历史面板空状态: 显示一个「空地图」SVG 插画
- 插件面板: 保持现状（功能性为主）

### 3.7 费用记录卡片 (ExpenseCard)

**当前缺失**: 目前前端没有专门的费用卡片组件

**新增方案**:
- 新增 `ExpenseCard.tsx` 组件
- 费用分类用彩色圆环图（纯 CSS/SVG 实现）
- 各类别费用用带图标的小条形展示

### 3.8 汇率卡片 (CurrencyCard)

**当前缺失**: 同样缺少前端组件

**新增方案**:
- 新增 `CurrencyCard.tsx` 组件
- 货币对用国旗 emoji 或 SVG 小图标区分
- 汇率数字用大号等宽字体突出

---

## 四、SVG 设计规范

### 色彩体系（与 CSS 变量对齐）
```css
/* SVG 内使用以下变量，自动适配亮/暗模式 */
fill: var(--accent)        /* 主色 #4f8ef7 / #60a5fa */
fill: var(--text-muted)    /* 装饰色 #94a3b8 / #64748b */
stroke: var(--border)      /* 边框色 */
opacity: 0.1~0.3           /* 背景装饰透明度 */
```

### 尺寸规范
| 用途 | 尺寸 | 格式 |
|------|------|------|
| Hero 插画 | 400x300 | SVG with viewBox |
| 卡片背景装饰 | 200x150 | SVG, opacity 0.08~0.15 |
| 城市剪影 | 120x80 | SVG, 单色轮廓 |
| 场景图标 | 48x48 | SVG |
| 状态徽章 | 24x24 | SVG |
| 天气图标 | 32x32 | SVG |

### 动画规范
- 浮动: `float` 6s ease-in-out infinite（已有）
- 淡入: `fade-in-up` 0.35s ease-out（已有）
- 脉冲: `glow-pulse` 2s ease-in-out infinite（已有）
- 新增：飞行路径 `fly-path` 3s linear infinite
- 新增：雷达扫描 `radar-sweep` 2s linear infinite

---

## 五、实施步骤

### Phase 1: 基础资源建设（优先级最高）
1. 创建 `welcome-hero.svg` - 欢迎页 Hero 插画
2. 创建 7 个城市剪影 SVG
3. 创建 5 个场景插画 SVG
4. 优化 `error.svg`，增加暗色模式支持
5. 创建 `thinking.svg` 思考动画

### Phase 2: 组件改造
1. 改造 `ChatPanel.tsx` - 欢迎页升级
2. 改造 `ItineraryCard.tsx` - 城市背景 + 路线概览
3. 改造 `EventCard.tsx` - 路线可视化
4. 改造 `InfoCard.tsx` - 天气图标
5. 改造 `ThinkingIndicator.tsx` - 品牌动画

### Phase 3: 新增组件
1. 新增 `CityIllustration.tsx` - 城市插画映射
2. 新增 `WeatherIcon.tsx` - 天气图标映射
3. 新增 `ExpenseCard.tsx` - 费用展示
4. 新增 `CurrencyCard.tsx` - 汇率展示
5. 在 `ResultDashboard.tsx` 中注册新卡片

### Phase 4: 侧边栏美化
1. 各面板空状态插画替换
2. 增加微交互动画

### Phase 5: 全局打磨
1. 暗色模式全面测试
2. 移动端响应式适配
3. 性能优化（SVG 压缩、懒加载）
4. 无障碍适配（alt 文本、aria 标签）

---

## 六、性能考量

| 措施 | 说明 |
|------|------|
| SVG 内联 vs 外链 | Hero 插画用外链 `<img>`，小图标考虑内联以便用 CSS 变量 |
| 懒加载 | 城市/场景 SVG 仅在对应卡片渲染时加载 |
| SVG 压缩 | 所有 SVG 使用 SVGO 压缩，目标 < 5KB/个 |
| 缓存策略 | 静态资源走 Vite 的 content hash 缓存 |
| 总增量 | 预计新增 ~20 个 SVG 文件，总计 < 100KB |

---

## 七、效果对比

| 模块 | 优化前 | 优化后 |
|------|--------|--------|
| 欢迎页 | 1 个 SVG + 纯文字 | Hero 插画 + 动画 + 扩展快捷入口 |
| 行程卡片 | emoji 图标 + 文字列表 | 城市剪影背景 + SVG 图标 + 路线概览 |
| 事件卡片 | 2x2 文字网格 | 路线可视化 + 场景插画 |
| 天气信息 | 纯文字 | 天气 SVG 图标 + 大号温度 |
| 思考状态 | 三个圆点 | 飞机飞行品牌动画 |
| 侧边栏空状态 | 小图标 + 2 行文字 | 主题插画 + 引导文案 |
| 费用/汇率 | 无专门组件 | 数据可视化卡片 |
