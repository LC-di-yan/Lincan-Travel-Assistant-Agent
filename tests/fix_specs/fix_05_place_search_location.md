# 修复文档 05：place-search 位置限定提取与城市识别

> **并行窗口专属文档** —— 本文档只修改 `.claude/skills/place-search/script/agent.py` 的 `_extract_city` 与 `_extract_location_context`。其他窗口同时修改同文件的其他函数，请勿越界。

## 修复范围

- **文件**：`.claude/skills/place-search/script/agent.py`
- **修改区域**：
  - `_COMMON_CITIES` 列表（约 29-61 行，仅扩展不删）
  - `_extract_city` 方法（约 471-477 行）
  - `_extract_location_context` 方法（约 481-526 行）
  - 新增模块级常量 `_UNIVERSITY_CITY_MAP`（高校→城市映射）
- **禁止修改**（其他窗口负责）：
  - `_is_restaurant_query`（约 205-224 行，→ 文档 06）
  - `_is_scenic_query`（约 349-364 行，→ 文档 06）
  - `_extract_food_params` / `_extract_scenic_params` / `_extract_search_params`
  - `_hotel_search` / `_restaurant_search` / `_scenic_search` 等 API 调用方法
  - `_build_result` / `_build_restaurant_result` / `_build_scenic_result`

## 涉及 Bug

| Bug ID | 用例 ID | 类别 | 查询 | 期望 |
|--------|---------|------|------|------|
| BUG-025 | LC-001 | location_context_over_extract | 上海大学附近的酒店 | place_city=上海, keywords 含"上海大学" |
| BUG-026 | LC-002 | location_context_over_extract | 北京大学周边的民宿 | place_city=北京, keywords 含"北京大学" |
| BUG-027 | LC-003 | location_context_over_extract | 复旦大学邯郸校区附近酒店 | place_city=上海 |

共 3 条。

## 根因

`.claude/skills/place-search/script/agent.py:481-526` `_extract_location_context` 用 `([一-龥]{2,6}(区|镇|...|大学|...))` 提取地标，存在两个问题：

1. **城市被剥离**：`_extract_location_context` 在 487-490 行先 `re.sub(rf"{city}市?", "", q)` 移除已识别城市，导致"上海大学附近的酒店"中"上海"被移除，剩余"大学附近的酒店"，地标正则匹配到"大学"但已被污染，最终 keywords 拼成"酒店"而非"上海大学 酒店"（BUG-025/026）。
2. **隐含城市无法识别**：`_extract_city`（471-477 行）只在 `_COMMON_CITIES` 中查找，"复旦大学邯郸校区附近酒店"中"上海"未显式出现，`_extract_city` 返回空（BUG-027）。

## 修复方案

### 步骤 1：新增高校→城市映射

在 `_COMMON_CITIES` 之后（约 62 行）新增：

```python
# 高校 → 所在城市映射（用于 _extract_city 从校名推断城市）
_UNIVERSITY_CITY_MAP = {
    # 北京
    "北京大学": "北京", "清华大学": "北京", "中国人民大学": "北京", "北京师范大学": "北京",
    "北京航空航天大学": "北京", "北京理工大学": "北京", "中国农业大学": "北京",
    # 上海
    "复旦大学": "上海", "上海交通大学": "上海", "同济大学": "上海", "华东师范大学": "上海",
    "上海大学": "上海", "华东理工大学": "上海", "上海财经大学": "上海",
    # 其他
    "浙江大学": "杭州", "南京大学": "南京", "中山大学": "广州", "武汉大学": "武汉",
    "四川大学": "成都", "厦门大学": "厦门", "山东大学": "济南", "南开大学": "天津",
    "西安交通大学": "西安", "华中科技大学": "武汉", "湖南大学": "长沙", "重庆大学": "重庆",
}
```

### 步骤 2：修改 `_extract_city` 支持高校推断

将 `_extract_city`（约 471-477 行）改为：

```python
    def _extract_city(self, query: str) -> str:
        """从查询中提取城市名，仅匹配已知城市列表或高校名。"""
        q = (query or "").strip()
        # 1. 先匹配已知城市
        for city in _COMMON_CITIES:
            if city in q:
                return city
        # 2. 再匹配高校名（从校名推断城市）
        for uni, city in _UNIVERSITY_CITY_MAP.items():
            if uni in q:
                return city
        return ""
```

### 步骤 3：修改 `_extract_location_context` 保留完整地标

将 `_extract_location_context`（约 481-526 行）中的城市移除逻辑改为"只移除独立的城市词，不移除城市作为高校名前缀的部分"：

```python
    def _extract_location_context(self, query: str, city: str) -> str:
        """
        从查询中提取区/镇/街道级位置限定词，用于拼入 API keywords 实现精准搜索。
        如 "揭阳市揭东区锡场镇附近" → city="揭阳", 返回 "揭东区锡场镇附近"
        """
        q = query
        if city:
            # 只移除"XX市"形式，不移除"XX大学"中的城市前缀
            q = re.sub(rf"{city}市", "", q)
            # 若查询含"XX大学"且该大学在 _UNIVERSITY_CITY_MAP，保留完整校名作为地标
            # 不再移除裸 city（避免"上海大学"→"大学"）

        # 移除住宿类型关键词
        for kw in _ACCOMMODATION_KEYWORDS:
            q = q.replace(kw, "")

        # 移除疑问词 / 动词 / 量词
        for word in ["有没有", "有哪些", "有什么", "帮我找", "帮我查", "搜索", "找一下",
                       "查一下", "推荐", "附近", "周边", "有没有", "哪家", "哪个",
                       "的", "吗", "呢", "啊", "吧", "有", "?", "？"]:
            q = q.replace(word, " ")

        # 提取区/镇/县/街道/路/景点/地标 级别的行政或地理名称
        location_match = re.search(
            r"([一-龥]{2,6}(?:区|镇|县|乡|街道|路|街|村|景区|公园|广场|站|商圈"
            r"|大学|学院|中学|小学|学校|医院|大厦|大楼|商场|购物中心"
            r"|地铁站|火车站|机场|码头|汽车站|高铁站"
            r"|山|湖|河|海|寺|庙|塔|桥|塔|宫|陵|墓))",
            q,
        )
        # 未匹配行政/地标后缀，尝试匹配"XX旁边/附近/周边"模式
        if not location_match:
            location_match = re.search(
                r"([一-龥]{2,10})(?:旁边|附近|周边|对面|楼下|边上|一带|附近一带|跟前)",
                q,
            )
        if location_match:
            # 截取匹配位置及前后上下文
            start = max(0, location_match.start() - 2)
            end = min(len(q), location_match.end() + 4)
            context = q[start:end].strip()
            # 清理多余空格
            context = re.sub(r"\s+", "", context)
            if context:
                return context

        return ""
```

关键变更：
- 第 488-490 行 `re.sub(rf"{city}市?", "", q)` 改为 `re.sub(rf"{city}市", "", q)`，**只移除"XX市"不移除裸城市名**。这样"上海大学附近的酒店"中"上海"被保留，地标正则能匹配到"上海大学"。

### 步骤 4：验证 keywords 拼接

`_extract_search_params`（约 528-580 行）会调用 `_extract_location_context` 并拼入 keywords。修复后：
- "上海大学附近的酒店"：city=上海，`_extract_location_context` 返回"上海大学"，keywords="上海大学 酒店"（BUG-025 期望）
- "北京大学周边的民宿"：city=北京，返回"北京大学"，keywords="北京大学 民宿"（BUG-026 期望）
- "复旦大学邯郸校区附近酒店"：city=上海（步骤 2 高校推断），返回"复旦大学邯郸校区"，keywords="复旦大学邯郸校区 酒店"（BUG-027 期望）

## 验证

```bash
python tests/logic_audit/runner.py
```

期望：
- BUG-025（LC-001）：place_city=上海, place_keywords 含"上海大学" → 通过
- BUG-026（LC-002）：place_city=北京, place_keywords 含"北京大学" → 通过
- BUG-027（LC-003）：place_city=上海 → 通过

### 手工抽检

```bash
python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('psa', '.claude/skills/place-search/script/agent.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
a = m.PlaceSearchAgent()
for q in ['上海大学附近的酒店', '北京大学周边的民宿', '复旦大学邯郸校区附近酒店', '中关村地铁站附近的酒店', '外滩附近的酒店']:
    city = a._extract_city(q)
    params = a._extract_search_params(q, city)
    print(f'{q:30} city={city:6} keywords={params[\"keywords\"]}')
"
```

期望：
- `上海大学附近的酒店` city=上海 keywords='上海大学 酒店'
- `北京大学周边的民宿` city=北京 keywords='北京大学 民宿'
- `复旦大学邯郸校区附近酒店` city=上海 keywords='复旦大学邯郸校区 酒店'
- `中关村地铁站附近的酒店` city=北京 keywords='中关村地铁站 酒店'（LC-004，原本 city=空，现在仍可能空——中关村不在 _COMMON_CITIES，需步骤 2 高校映射或新增地标映射。若仍空，属已知限制，用例期望是 agents=['hotel_search']，仍通过）
- `外滩附近的酒店` city=上海（若 _COMMON_CITIES 无"外滩"，city 仍空，但 LC-005 用例期望仅 agents=['hotel_search']，通过）

> ⚠️ LC-004/005 的 city 提取仍可能为空，但用例期望不校验 city，所以不影响通过。若需完整修复，可扩展 `_UNIVERSITY_CITY_MAP` 为 `_LANDMARK_CITY_MAP` 含"外滩→上海""中关村→北京"等，但本文档不强制。

## 并行注意事项

- **文档 06** 修改 `_is_restaurant_query`（205-224 行）和 `_is_scenic_query`（349-364 行），本文档修改 `_extract_city`（471-477 行）和 `_extract_location_context`（481-526 行），区域相距 200+ 行，不冲突。
- **文档 02** 修改 `intention_agent.py` 的模块常量，本文档修改 `place-search/script/agent.py`，不同文件，不冲突。
- **文档 01/03/04** 修改 `intention_agent.py`，本文档修改 `place-search/script/agent.py`，不冲突。

## 不做的事

- 不修改 `_is_restaurant_query` / `_is_scenic_query`（→ 文档 06）
- 不修改 API 调用方法（`_hotel_search` / `_restaurant_search` / `_scenic_search`）
- 不修改结果构建方法（`_build_*`）
- 不扩展 `_LANDMARK_CITY_MAP`（地标→城市映射，留作后续优化）
