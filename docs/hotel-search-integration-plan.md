# hotel-search Skill 接入系统方案

## 概述

将已封装并独立测试通过的 `hotel-search` Skill 接入 Aligo 旅行助手的意图识别 → 调度 → 前端展示全链路。

当前状态：Skill 文件已就绪，独立测试通过（`test_hotel_search.py`），高德 API 调用验证无误。

---

## 一、涉及文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `agents/intention_agent.py` | 新增快速路由规则 + LLM prompt 补充 |
| 修改 | `agents/lazy_agent_registry.py` | 新增 `hotel_search` → `hotel-search` legacy mapping |
| 修改 | `data/plugin_config.json` | 新增 `hotel-search` 启用配置 |
| 新建 | `web/src/components/Results/HotelCard.tsx` | 酒店搜索结果卡片组件 |
| 修改 | `web/src/api/types.ts` | 新增 `HotelItem`、`HotelResultData` 类型 |
| 修改 | `web/src/components/Results/ResultDashboard.tsx` | 新增 `hotel_search` → `HotelCard` 路由 |

共 **4 修改 + 2 新建** 个文件。

---

## 二、各文件修改详情

### 2.1 `agents/intention_agent.py`

#### 2.1.1 新增快速路由规则

在 `_MEMORY_PATTERNS` 之后、`_fast_match` 函数之前新增：

```python
_HOTEL_PATTERNS = [
    re.compile(r"(.{2,6})[的有]?(?:哪些|什么|哪家).*?(?:酒店|民宿|宾馆|旅馆|客栈|青旅|住宿)"),
    re.compile(r"(?:找|查|搜).{0,6}(.{2,6}).*?(?:酒店|民宿|宾馆|旅馆|客栈)"),
    re.compile(r"(?:帮我找|帮我查|搜索|推荐|看看?).*?(?:酒店|民宿|宾馆|旅馆|客栈|住宿)"),
    re.compile(r"(?:酒店|民宿|宾馆|旅馆|客栈|住宿).*?(?:推荐|搜索|查询)"),
]
```

在 `_fast_match` 函数中，于 `_MEMORY_PATTERNS` 处理之后、`return None` 之前新增：

```python
    # 酒店搜索
    for p in _HOTEL_PATTERNS:
        m = p.search(q)
        if m:
            return {
                "reasoning": "规则匹配: 酒店搜索关键词",
                "intents": [{"type": "hotel_search", "confidence": 0.92, "description": "酒店/民宿搜索", "reason": "匹配酒店搜索模式"}],
                "key_entities": {"other": q},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "hotel_search", "priority": 1, "reason": "搜索住宿", "expected_output": "酒店列表"}],
            }
```

#### 2.1.2 LLM Prompt 补充

在意图识别 prompt 的意图类型列表中新增一行：

```
- 酒店搜索 → hotel_search: 查酒店、找民宿、推荐住宿、XX有什么酒店、XX附近的宾馆
```

在 `agent_schedule` JSON 示例区域新增 `hotel_search` 的 agent_name 示例。

在优先级说明区域将 `hotel_search` 加入 P1：

```
P1: memory_query, train_ticket, preference, information_query, rag_knowledge, expense_tracking, currency_conversion, translation, visa_info, hotel_search
P2（依赖P1结果）: itinerary_planning
```

---

### 2.2 `agents/lazy_agent_registry.py`

在 `_legacy_mapping` 字典中新增一行：

```python
"hotel_search": "hotel-search",
```

注册器会自动扫描 `.claude/skills/hotel-search/script/agent.py`，发现 `HotelSearchAgent` 子类并完成懒加载。此映射仅需连接 `intent_type` 到目录名的对应关系。

---

### 2.3 `data/plugin_config.json`

新增配置项：

```json
"hotel-search": {
  "enabled": true
}
```

---

### 2.4 `web/src/api/types.ts`

新增类型定义：

```typescript
// ===== 酒店搜索 =====

export interface HotelItem {
  id: string
  name: string
  address: string
  rating: string
  cost: string
  tel: string
  photo: string
  distance: string
  type: string
}

export interface HotelResultData {
  city: string
  keyword: string
  count: number
  summary: string
  hotels: HotelItem[]
  sources: { title: string; url: string }[]
}
```

---

### 2.5 `web/src/components/Results/HotelCard.tsx`（新建）

卡片布局设计：

```
┌─────────────────────────────────────────────┐
│  🏨 {city}酒店搜索 · 共{count}家             │
│  ─────────────────────────────────────────── │
│  {summary}                                   │
│                                              │
│  ┌──────────┬──────────────────────────────┐ │
│  │          │ {name}                 4.7★  │ │
│  │  [图片]  │ {address}                     │ │
│  │          │ 价格: ¥298-598  电话: xxx     │ │
│  │          │ 距离: 245m                    │ │
│  └──────────┴──────────────────────────────┘ │
│  ┌──────────┬──────────────────────────────┐ │
│  │          │ {name}                 4.4★  │ │
│  │  [图片]  │ ...                           │ │
│  └──────────┴──────────────────────────────┘ │
│                                              │
│  数据来源: 高德地图                           │
└─────────────────────────────────────────────┘
```

核心逻辑：
- 头部展示城市名 + 结果总数
- 摘要文字（来自 agent 返回的 `summary` 字段）
- 酒店列表：每一项左图右文，展示名称、地址、评分、价格区间、电话、距离
- 高德地图 logo 链接作为数据来源标注
- 无结果时显示空状态占位

Props 接口：

```typescript
interface HotelCardProps {
  data: HotelResultData
}
```

---

### 2.6 `web/src/components/Results/ResultDashboard.tsx`

在 `ResultCard` 组件的 switch-case 中新增路由：

```typescript
case 'hotel_search':
  return <HotelCard data={inner as HotelResultData} />
```

放在 `information_query` case 之后即可。

---

## 三、数据流

```
用户输入: "揭阳锡场镇附近有酒店吗"
    │
    ▼
IntentionAgent
    ├─ 快速路由: _HOTEL_PATTERNS 命中
    │   → intent_type: "hotel_search"
    │   → agent_name: "hotel_search", priority: 1
    │
    ├─ (或 LLM 识别) → 同上的结构化决策
    │
    ▼
OrchestrationAgent
    ├─ 根据 agent_schedule 调度
    ├─ 从 LazyAgentRegistry 懒加载 HotelSearchAgent
    ├─ 构造 Msg(content=rewritten_query) 传入 agent.reply()
    │
    ▼
HotelSearchAgent.reply()
    ├─ _extract_city("揭阳锡场镇附近有酒店吗") → "揭阳"
    ├─ _extract_search_params(..., city="揭阳")
    │   ├─ 住宿关键词: "酒店"
    │   ├─ 位置限定: "揭东区锡场镇" (via _extract_location_context)
    │   └─ keywords = "揭东区锡场镇 酒店"
    ├─ _hotel_search(city="揭阳", params)
    │   └─ GET /v3/place/text?keywords=揭东区锡场镇+酒店&city=揭阳&...
    ├─ _build_result(...) → 结构化 JSON
    │
    ▼
SSE → 前端 ChatPanel
    ├─ agent_result event: { agent_name: "hotel_search", data: {...} }
    │
    ▼
ResultDashboard → ResultCard
    ├─ switch(agent_name) → case "hotel_search"
    └─ <HotelCard data={inner} />
```

---

## 四、意图识别优先级

| 场景 | 触发关键词 | 意图 | 优先级 |
|------|-----------|------|--------|
| "北京有哪些酒店" | 城市+酒店 | hotel_search | P1 |
| "帮我找成都的民宿" | 找+城市+民宿 | hotel_search | P1 |
| "深圳五星级酒店" | 城市+星级+酒店 | hotel_search | P1 |
| "揭阳锡场镇附近住宿" | 城市+乡镇+住宿 | hotel_search | P1 |
| "万豪酒店"（无城市） | 仅品牌名 | 需反问 → hotel_search | — |

### 意图消歧

- **hotel_search vs information_query**：含"酒店/民宿/住宿/客栈"等住宿关键词 → hotel_search；通用"查一下XX" → information_query
- **hotel_search vs expense_tracking**："住宿花了500" → expense_tracking（含金额，记账意图）；"深圳有什么住宿" → hotel_search（查询意图）
- **hotel_search + event_collection**："我想去北京出差，帮我看看有什么酒店" → event_collection (P1, 提取行程要素) + hotel_search (P1, 搜酒店)，两者可并行调度

---

## 五、降级与边界情况

| 场景 | 行为 |
|------|------|
| 无城市名 | Agent 返回 `query_success=false`，前端显示"请说明具体城市" |
| API Key 未配置 | Agent 抛出异常，前端显示"AMAP_API_KEY 未配置" |
| API 返回空 | Agent 返回 count=0 + 友好提示，前端显示空状态 |
| 网络超时 | 20s 超时，Agent 返回失败 |
| 未知城市 | 城市白名单匹配不到 → "未识别到城市" |

---

## 六、不纳入本次范围

- 分页/加载更多（第一版 `offset=15` 够用）
- 用户偏好联动（用户存的酒店品牌偏好自动填入搜索）
- 酒店详情页（需额外调用 `place/detail` API）
- 地图展示（高德 JS API 需前端额外接入）
- 与 `plan-trip` 的深度联动（行程规划中自动搜酒店）

---

## 七、接入顺序建议

1. **后端先行**：先改 `intention_agent.py` + `lazy_agent_registry.py` + `plugin_config.json`，重启后端验证意图识别和调度
2. **前端跟进**：再新建 `HotelCard.tsx` + 改 `types.ts` + `ResultDashboard.tsx`，验证完整链路
3. **端到端测试**：用 Web UI 发真实请求，验证从输入到卡片展示的全流程
