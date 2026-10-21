# 修复文档 04：天气分支多意图扩展

> **并行窗口专属文档** —— 本文档只修改 `agents/intention_agent.py` 的 `_fast_match` 天气分支（约 317-348 行）。其他窗口同时修改同文件的其他区域，请勿越界。

## 修复范围

- **文件**：`agents/intention_agent.py`
- **修改区域**：
  - `_fast_match` 函数内的天气分支（约 317-348 行）
- **禁止修改**（其他窗口负责）：
  - `_fast_match` 顶部差旅信号检测（→ 文档 01）
  - `_fast_match` 其他分支（记账/酒店/餐厅/景点/汇率/翻译/火车票/记忆）
  - `_WEATHER_PATTERNS` 模块级正则（未发现 bug，不动）
  - `_HOTEL_PATTERNS` / `_RESTAURANT_PATTERNS` / `_SCENIC_PATTERNS` 等模块级正则（→ 文档 02）
  - `_CITY_KEYWORDS` / `_resolve_elliptical`（→ 文档 03）

## 涉及 Bug

| Bug ID | 用例 ID | 类别 | 查询 | 期望 agents |
|--------|---------|------|------|------------|
| BUG-028 | MI-002 | multi_intent_collapse | 广州天气和美食 | information_query + restaurant_search |
| BUG-029 | MI-003 | multi_intent_collapse | 北京景点和酒店 | scenic_search + hotel_search |
| BUG-030 | MI-004 | multi_intent_collapse | 杭州天气和景点和美食 | information_query + scenic_search + restaurant_search |

共 3 条。

> **注意**：BUG-029（"北京景点和酒店"）实际命中酒店分支而非天气分支，根因是酒店/餐厅/景点分支互斥。但本文档边界只到天气分支，BUG-029 的修复需在酒店/餐厅/景点分支也加多意图附加逻辑——**这超出本文档边界**。本文档只修天气分支的多意图附加（BUG-028/030），BUG-029 标记为"需文档 02 配合"或留给后续。

## 根因

`agents/intention_agent.py:317-348` 天气分支只附加 `hotel_search`，对"天气+美食""天气+景点"等组合不会生成多 agent_schedule。代码片段：

```python
# 当前逻辑（约 334-348 行）
hotel_words = ["住宿", "酒店", "宾馆", "民宿", "旅馆", "青旅", "客栈", "招待所", "住"]
has_hotel = any(w in q for w in hotel_words)
agent_schedule = [{"agent_name": "information_query", "priority": 1, "reason": "查天气", "expected_output": "天气信息"}]
intents = [{"type": "information_query", "confidence": 0.9, "description": "天气查询", "reason": "匹配天气模式"}]
if has_hotel:
    agent_schedule.append({"agent_name": "hotel_search", "priority": 1, "reason": "查住宿", "expected_output": "酒店列表"})
    intents.append({"type": "hotel_search", "confidence": 0.85, "description": "酒店搜索", "reason": "查询含住宿关键词"})
```

只检测 `hotel_words`，不检测餐厅/景点关键词。

## 修复方案

### 步骤 1：扩展天气分支的多意图检测

修改 `_fast_match` 天气分支（约 317-348 行），在 `has_hotel` 检测之后新增 `has_restaurant` / `has_scenic` 检测，并附加对应 agent_schedule。

```python
    # 天气
    for p in _WEATHER_PATTERNS:
        m = p.search(q)
        if m:
            city = m.group(1).strip() if m.lastindex and m.group(1) else ""
            # 也提取城市从住宿关键词
            if not city:
                for hq in ["住宿", "酒店", "宾馆", "民宿", "旅馆", "青旅", "客栈"]:
                    if hq in q:
                        for c in _CITY_KEYWORDS:
                            if c in q:
                                city = c
                                break
                        break
            # 有对话历史但没提取到城市 → 交给 LLM 用历史补全
            if not city and _has_history:
                return None

            agent_schedule = [{"agent_name": "information_query", "priority": 1, "reason": "查天气", "expected_output": "天气信息"}]
            intents = [{"type": "information_query", "confidence": 0.9, "description": "天气查询", "reason": "匹配天气模式"}]

            # ── 多意图附加：检测住宿/餐厅/景点关键词 ──
            hotel_words = ["住宿", "酒店", "宾馆", "民宿", "旅馆", "青旅", "客栈", "招待所"]
            has_hotel = any(w in q for w in hotel_words)
            if has_hotel:
                agent_schedule.append({"agent_name": "hotel_search", "priority": 1, "reason": "查住宿", "expected_output": "酒店列表"})
                intents.append({"type": "hotel_search", "confidence": 0.85, "description": "酒店搜索", "reason": "查询含住宿关键词"})

            # 餐厅/美食关键词（复用 _RESTAURANT_KEYWORDS 与 _CUISINE_KEYWORDS）
            restaurant_words = ["美食", "好吃", "餐厅", "餐馆", "饭店", "饭馆", "小吃", "火锅",
                                "川菜", "粤菜", "湘菜", "日料", "韩餐", "西餐", "烧烤", "海鲜"]
            has_restaurant = any(w in q for w in restaurant_words)
            if has_restaurant:
                agent_schedule.append({"agent_name": "restaurant_search", "priority": 1, "reason": "查美食", "expected_output": "餐厅列表"})
                intents.append({"type": "restaurant_search", "confidence": 0.85, "description": "餐厅搜索", "reason": "查询含美食关键词"})

            # 景点关键词
            scenic_words = ["景点", "景区", "公园", "好玩", "旅游", "打卡", "名胜", "风景"]
            has_scenic = any(w in q for w in scenic_words)
            if has_scenic:
                agent_schedule.append({"agent_name": "scenic_search", "priority": 1, "reason": "查景点", "expected_output": "景点列表"})
                intents.append({"type": "scenic_search", "confidence": 0.85, "description": "景点搜索", "reason": "查询含景点关键词"})

            return {
                "reasoning": "规则匹配: 天气查询" +
                             ("+酒店搜索" if has_hotel else "") +
                             ("+餐厅搜索" if has_restaurant else "") +
                             ("+景点搜索" if has_scenic else ""),
                "intents": intents,
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": agent_schedule,
            }
```

### 步骤 2：处理多城市错配（部分缓解）

BUG-028/030 是单城市多意图，本文档修复后可解决。但"北京天气和上海酒店"这类双城市错配（WM-001/002/004，当前通过用例）仍存在：`city` 只提取首个，hotel_search 复用同一 city。

**本步骤不修复双城市错配**（需重构城市提取逻辑，超出天气分支边界），只在注释中标注已知限制：

```python
# 已知限制：当查询含多个城市（如"北京天气和上海酒店"）时，
# 仅提取首个城市，后续 hotel_search/restaurant_search 复用该城市。
# 完整修复需重构城市提取为列表，属文档 02/03 的 _CITY_KEYWORDS 范畴。
```

## 验证

```bash
python tests/logic_audit/runner.py
```

期望：
- BUG-028（MI-002 "广州天气和美食"）：agents 含 `information_query` + `restaurant_search`，通过
- BUG-030（MI-004 "杭州天气和景点和美食"）：agents 含 3 个，通过
- BUG-029（MI-003 "北京景点和酒店"）：**仍不通过**（命中酒店分支而非天气分支，超出本文档边界）。需文档 02 在 `_HOTEL_PATTERNS` / `_SCENIC_PATTERNS` 分支也加多意图附加，或单独建文档 07。

### 手工抽检

```bash
python -c "
from agents.intention_agent import _fast_match
import json
queries = ['广州天气和美食', '杭州天气和景点和美食', '上海天气和酒店']
for q in queries:
    r = _fast_match(q, [])
    if r:
        agents = [a['agent_name'] for a in r['agent_schedule']]
        print(f'{q:20} -> {agents}')
    else:
        print(f'{q:20} -> LLM')
"
```

期望：
- `广州天气和美食` → `['information_query', 'restaurant_search']`
- `杭州天气和景点和美食` → `['information_query', 'scenic_search', 'restaurant_search']`
- `上海天气和酒店` → `['information_query', 'hotel_search']`

## 并行注意事项

- **文档 01** 修改 `_fast_match` 顶部（267-282 行），本文档修改天气分支（317-348 行），相距 35+ 行，git 行级合并不冲突。
- **文档 02** 修改模块级正则，本文档不改模块级正则（只读用 `_RESTAURANT_KEYWORDS` 等），不冲突。但本文档步骤 1 中 `restaurant_words` / `scenic_words` 是手写列表，未复用 `_RESTAURANT_KEYWORDS` / `_SCENIC_KEYWORDS`。若文档 02 修改了这些常量，本文档的手写列表可能与之不同步。**建议**：本文档直接 `from agents.intention_agent import _RESTAURANT_KEYWORDS, _SCENIC_KEYWORDS` 复用，但需注意这些是 `sorted` 后的列表，用 `any(w in q for w in _RESTAURANT_KEYWORDS)` 即可。
- **文档 03** 修改 `_CITY_KEYWORDS`，本文档天气分支 `for c in _CITY_KEYWORDS` 会读到修改后的集合，行为一致，不冲突。

## 不做的事

- 不修复 BUG-029（景点+酒店互斥分支，超出天气分支边界）
- 不修复双城市错配（WM 系列，需重构城市提取）
- 不修改 `_WEATHER_PATTERNS`
- 不修改 `_fast_match` 顶部与其他分支
