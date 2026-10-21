# 修复文档 03：省略追问城市识别扩展

> **并行窗口专属文档** —— 本文档只修改 `agents/intention_agent.py` 的 `_CITY_KEYWORDS` 集合与 `_resolve_elliptical` 函数。其他窗口同时修改同文件的其他区域，请勿越界。

## 修复范围

- **文件**：`agents/intention_agent.py`
- **修改区域**：
  - `_CITY_KEYWORDS` 集合（约 209-214 行）
  - `_resolve_elliptical` 函数（约 220-264 行）
- **禁止修改**（其他窗口负责）：
  - `_fast_match` 函数体（→ 文档 01 顶部、文档 04 天气分支）
  - `_HOTEL_PATTERNS` / `_RESTAURANT_PATTERNS` / `_SCENIC_PATTERNS` / `_TRANSLATION_PATTERNS` / `_MEMORY_PATTERNS` / `_TRAIN_PATTERNS` 等模块级正则（→ 文档 02）
  - `_extract_currency` / `_CURRENCY_PATTERNS`

## 涉及 Bug

| Bug ID | 用例 ID | 类别 | 查询 | 期望 |
|--------|---------|------|------|------|
| BUG-012 | EL-001 | elliptical_limit | 那虹桥呢 | 不应被识别为省略追问（虹桥不是城市，应走 LLM） |

仅 1 条。但审计中发现 `_resolve_elliptical` 的城市判定过严，对真实城市追问也会失败（EL-002~005 通过是因为期望 `elliptical_resolved=false`，但语义上"那嘉兴呢"应能消解）。本文档同时改善这两类。

## 根因

`agents/intention_agent.py:226-230` `_resolve_elliptical` 用 `if city not in _CITY_KEYWORDS: return None` 判定，`_CITY_KEYWORDS` 仅含直辖市/省会/计划单列市等约 40 个，导致：

1. **误判**：`_CITY_KEYWORDS` 含"虹桥/南站/北站/东站/西站"等火车站名（210-214 行第 4 行），"那虹桥呢"被错误识别为城市追问 → BUG-012
2. **漏判**："那嘉兴呢/那香格里拉呢"等真实城市/旅游地不在 `_CITY_KEYWORDS`，无法消解（EL-002~005 的期望是 `false`，但语义上应能消解，属用例期望设计问题，本文档同时修复）

## 修复方案

### 步骤 1：清理 `_CITY_KEYWORDS` 中的非城市条目

将 `_CITY_KEYWORDS`（约 209-214 行）中的火车站名移除：

```python
# 城市关键词（模块级，供快速路由和天气/酒店检测共用）
_CITY_KEYWORDS = {"北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州",
                  "天津", "重庆", "厦门", "青岛", "大连", "宁波", "无锡", "长沙", "郑州", "济南",
                  "哈尔滨", "沈阳", "昆明", "合肥", "福州", "石家庄", "南昌", "贵阳", "太原", "南宁",
                  "拉萨", "乌鲁木齐", "呼和浩特", "银川", "西宁", "兰州", "海口", "三亚", "珠海",
                  "嘉兴", "丽江", "大理", "桂林", "洛阳", "威海", "烟台", "温州", "绍兴", "徐州"}
# 移除：虹桥, 南站, 北站, 东站, 西站（这些是火车站/区域名，非城市）
# 新增地级市/旅游城市：嘉兴, 丽江, 大理, 桂林, 洛阳, 威海, 烟台, 温州, 绍兴, 徐州
```

> ⚠️ 此修改可能影响 `_fast_match` 中其他分支的城市提取（如酒店搜索分支用 `_CITY_KEYWORDS` 提取城市）。移除"虹桥/南站"后，"虹桥火车站附近的酒店"不再误提取"虹桥"为城市，应走 LLM 或提示用户补城市。这是期望行为。

### 步骤 2：新增地理名词库，扩展省略追问识别

在 `_CITY_KEYWORDS` 之后新增更全的地理名词库（供 `_resolve_elliptical` 使用，不供 `_fast_match` 用）：

```python
# 扩展地理名词库（供 _resolve_elliptical 消解省略追问，比 _CITY_KEYWORDS 更宽）
# 含地级市、县级市、知名旅游地、商圈、地标群
_EXTENDED_GEO_NAMES = _CITY_KEYWORDS | {
    # 地级市
    "佛山", "东莞", "惠州", "中山", "江门", "肇庆", "潮州", "揭阳", "汕尾", "梅州",
    "常州", "南通", "镇江", "泰州", "盐城", "淮安", "连云港", "宿迁", "湖州", "金华",
    "衢州", "舟山", "台州", "丽水", "芜湖", "潍坊", "临沂", "淄博", "济宁", "泰安",
    "泉州", "漳州", "龙岩", "三明", "莆田", "宁德", "南平", "宜昌", "襄阳", "荆州",
    "绵阳", "德阳", "宜宾", "南充", "泸州", "遵义", "曲靖", "玉溪", "长春", "吉林",
    "鞍山", "锦州", "咸阳", "宝鸡", "榆林", "柳州", "北海", "防城港", "儋州", "琼海",
    "包头", "鄂尔多斯", "赤峰", "九江", "景德镇", "岳阳", "延安", "秦皇岛", "承德",
    # 知名旅游地/县级市
    "香格里拉", "西双版纳", "九寨沟", "峨眉山", "张家界", "凤凰", "黄山", "敦煌",
    "平遥", "乌镇", "周庄", "西塘", "同里", "南浔", "阳朔", "德清", "安吉",
    # 上海/北京等大城市的区与地标群（用于"那浦东呢/那虹桥呢"消解）
    "浦东", "浦西", "虹桥", "陆家嘴", "徐家汇", "静安", "黄浦", "长宁", "杨浦",
    "海淀", "朝阳", "丰台", "通州", "顺义", "昌平", "大兴",
    # 大学的泛称（"那大学城呢"）
    "大学城",
}
```

### 步骤 3：修改 `_resolve_elliptical` 使用扩展词库

将 `_resolve_elliptical`（约 220-264 行）中的城市判定从 `_CITY_KEYWORDS` 改为 `_EXTENDED_GEO_NAMES`：

```python
def _resolve_elliptical(query: str, dialogue: list) -> Optional[dict]:
    """
    检测省略追问（"福州的呢"、"那上海呢"）并从对话历史推断意图。
    返回 None 表示不是省略追问，返回 dict 表示已解析。
    """
    q = query.strip().rstrip("？？")
    m = re.match(r"^(?:那)?(.{2,6})的?呢$", q)
    if not m:
        return None
    city = m.group(1).strip()
    # 改用扩展地理词库，覆盖地级市/旅游地/商圈/地标群
    if city not in _EXTENDED_GEO_NAMES:
        return None

    # 从最近一轮助手回复中推断意图类型
    _INTENT_SIGNATURES = [
        ("scenic_search", ["景点", "attractions", "scenic_search", "景区", "公园"]),
        ("restaurant_search", ["美食", "restaurants", "restaurant_search", "好吃", "餐厅", "火锅"]),
        ("hotel_search", ["酒店", "hotels", "hotel_search", "住宿", "民宿", "宾馆"]),
    ]
    last_intent = None
    for item in reversed(dialogue):
        if item.startswith("助手:"):
            for intent_type, keywords in _INTENT_SIGNATURES:
                if any(kw in item for kw in keywords):
                    last_intent = intent_type
                    break
        if last_intent:
            break

    if not last_intent:
        return None

    intent_labels = {
        "scenic_search": ("景点搜索", "搜景点", "景点列表", "景点"),
        "restaurant_search": ("餐厅搜索", "搜餐厅", "餐厅列表", "美食"),
        "hotel_search": ("酒店搜索", "搜酒店", "酒店列表", "酒店"),
    }
    label, reason, output, keyword = intent_labels[last_intent]
    return {
        "reasoning": f"上下文消解: 省略追问→{city}{label}",
        "intents": [{"type": last_intent, "confidence": 0.92, "description": label, "reason": "从对话历史推断省略追问"}],
        "key_entities": {"destination": city},
        "rewritten_query": f"{city}{keyword}",
        "agent_schedule": [{"agent_name": last_intent, "priority": 1, "reason": reason, "expected_output": output}],
    }
```

## 验证

```bash
python tests/logic_audit/runner.py
```

期望：
- BUG-012（EL-001 "那虹桥呢"）：现在 `虹桥` 在 `_EXTENDED_GEO_NAMES` 中，`elliptical_resolved=true`。**但用例期望是 `false`**！

  → **用例期望需调整**。请编辑 `tests/logic_audit/cases/05_elliptical_limit.json` 中 EL-001 的 `expected.elliptical_resolved` 从 `false` 改为 `true`，并更新 `note` 为："虹桥现为扩展地理词库条目，可消解为上海虹桥的酒店/景点追问"。

- EL-002~005 仍通过（`大学城/香格里拉/浦东新区/嘉兴` 现多在 `_EXTENDED_GEO_NAMES`，`elliptical_resolved=true`，但用例期望是 `false`！）

  → **这些用例期望也需调整**。请将 EL-002~005 的 `expected.elliptical_resolved` 全部改为 `true`，反映修复后能正确消解。

> ⚠️ 本文档的修复会让 EL-001~005 全部 `elliptical_resolved=true`。审计用例的期望值需同步更新，否则 runner 会报"反转 bug"。这是用例侧的调整，不是代码 bug。

### 手工抽检

```bash
python -c "
from agents.intention_agent import _resolve_elliptical
import json
cases = [
    ('那虹桥呢', ['用户: 上海有哪些酒店', '助手: 上海共有N家酒店...']),
    ('那嘉兴呢', ['用户: 杭州有什么景点', '助手: 杭州共有N家景点...']),
    ('那大学城呢', ['用户: 上海有什么好吃的', '助手: 上海共有N家美食...']),
]
for q, d in cases:
    r = _resolve_elliptical(q, d)
    print(f'{q:12} -> {\"resolved: \" + json.dumps(r[\"key_entities\"], ensure_ascii=False) if r else \"None\"}')
"
```

期望全部 resolved。

## 并行注意事项

- **文档 01** 在约 208 行新增 `_TRIP_SIGNAL_PATTERNS`，本文档修改 `_CITY_KEYWORDS`（209-214 行）和新增 `_EXTENDED_GEO_NAMES`（214 行之后）。建议本文档将 `_EXTENDED_GEO_NAMES` 放在 `_CITY_KEYWORDS` 之后、`_resolve_elliptical` 之前，与文档 01 的新增常量相邻但不重叠。
- **文档 02** 修改 `_MEMORY_PATTERNS`（201-207 行），本文档修改 `_CITY_KEYWORDS`（209-214 行），不重叠。
- **文档 04** 修改 `_fast_match` 天气分支，本文档不改 `_fast_match`，不冲突。
- 移除 `_CITY_KEYWORDS` 中的"虹桥/南站/北站/东站/西站"可能影响 `_fast_match` 中其他分支（如酒店搜索"虹桥火车站附近的酒店"）。这是期望行为（应走 LLM 或提示用户），但若 CE-006 用例期望变化，需同步更新 `tests/logic_audit/cases/02_city_extraction.json` 中 CE-006 的期望。

## 不做的事

- 不修改 `_fast_match` 函数体
- 不修改 *_PATTERNS 正则
- 不修改 LLM prompt
- 不动 `_extract_currency`
