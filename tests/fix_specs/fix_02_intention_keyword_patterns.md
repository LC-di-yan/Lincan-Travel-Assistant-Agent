# 修复文档 02：intention_agent 关键词集与正则收紧

> **并行窗口专属文档** —— 本文档只修改 `agents/intention_agent.py` 的模块级关键词常量与正则。其他窗口同时修改同文件的其他区域，请勿越界。

## 修复范围

- **文件**：`agents/intention_agent.py`
- **修改区域**（仅模块级常量）：
  - `_HOTEL_KEYWORDS`（约 67-85 行）
  - `_RESTAURANT_KEYWORDS` / `_CUISINE_KEYWORDS`（约 87-110 行）
  - `_SCENIC_KEYWORDS` / `_SCENIC_PLACE_KEYWORDS`（约 113-136 行）
  - `_TRANSLATION_PATTERNS`（约 185-189 行）
  - `_TRAIN_PATTERNS` 中的日期正则部分（约 191-199 行，仅扩展日期捕获）
  - `_MEMORY_PATTERNS`（约 201-207 行）
- **禁止修改**（其他窗口负责）：
  - `_fast_match` 函数体（→ 文档 01 顶部、文档 04 天气分支）
  - `_CITY_KEYWORDS` / `_resolve_elliptical`（→ 文档 03）
  - `_extract_currency` / `_CURRENCY_PATTERNS`（本审计未发现 bug，不动）
  - `_EXPENSE_PATTERNS` / `_WEATHER_PATTERNS`（未发现 bug）

## 涉及 Bug

| Bug ID | 用例 ID | 类别 | 查询 | 修改目标 |
|--------|---------|------|------|---------|
| BUG-008 | KB-003 | keyword_too_broad | 他住的地方离公司很远 | HOTEL 关键词加动词限定 |
| BUG-009 | KB-004 | keyword_too_broad | 昨晚吃了一顿大餐 | RESTAURANT 关键词加动词限定 |
| BUG-010 | KB-005 | keyword_too_broad | 我们去逛逛街吧 | SCENIC 关键词加动词限定 |
| BUG-011 | DT-003 | date_extraction_gap | 中秋节去杭州旅游 | 日期正则覆盖节假日 |
| BUG-018 | MF-003 | memory_false_trigger | 去年去过北京，今年还想去 | _MEMORY_PATTERNS 收紧 |
| BUG-019 | MF-004 | memory_false_trigger | 记得上次去北京的时候 | _MEMORY_PATTERNS 补基线 |
| BUG-020 | MF-005 | memory_false_trigger | 我去过哪些地方旅游 | _MEMORY_PATTERNS 补基线 |
| BUG-021 | TL-001 | translation_lang_gap | 翻译成俄语 | 翻译白名单补俄语 |
| BUG-022 | TL-002 | translation_lang_gap | 用阿拉伯语怎么说 | 翻译白名单补阿拉伯语 |
| BUG-023 | TL-003 | translation_lang_gap | 翻译成西班牙语 | 翻译白名单补西班牙语 |
| BUG-024 | TL-005 | translation_lang_gap | translate to Russian | 英文白名单补 Russian |
| BUG-031 | TT-003 | train_ticket_ambiguity | 上海到杭州旅游 | _SCENIC_KEYWORDS 排除差旅上下文 |

共 12 条。

## 修复方案

### 2.1 关键词过宽（BUG-008/009/010）

**根因**：`_HOTEL_PATTERNS` 等用 `(.{2,8}?).*?(关键词)` 匹配，单关键词"住的地方/大餐/逛逛"在叙述句中误命中。

**方案**：不修改关键词集本身（关键词集是合理的），改为给 `_HOTEL_PATTERNS` / `_RESTAURANT_PATTERNS` / `_SCENIC_PATTERNS` 增加查询动词前置校验。在 `_fast_match` 的酒店/餐厅/景点分支入口处增加"必须同时含搜索动词"的判定。

> ⚠️ **边界**：本节只修改关键词相关的 *_KEYWORDS 集合与 *_PATTERNS 正则，**不修改 `_fast_match` 函数体**。函数体内的动词校验逻辑由文档 01 的差旅信号短路间接缓解（差旅信号走 LLM），剩余的纯叙述误命中需在正则层收紧。

具体修改 `_HOTEL_PATTERNS`（67-85 行），给每条正则的匹配前提加"查询动词"锚点。最简做法：在 `_HOTEL_PATTERNS` 之前新增一个动词集合，并在 `_fast_match` 调用前校验。但函数体归文档 01/04，所以本节只改正则，让正则本身更严：

```python
# 查询动词（必须出现才视为搜索类查询）
_SEARCH_VERBS = r"(?:有哪些|有什么|有啥|有没有|找[一]?下?|查[一]?下?|搜[一]?[下索]?|搜索|推荐|[看瞧]看?|帮我找|帮我查|附近|周边|哪里|哪儿|什么地方|哪家|哪[些个])"

_HOTEL_PATTERNS = [
    # "北京有哪些酒店" / "上海有没有住的地方"
    re.compile(rf"(.{{2,6}})[的有]?(?:哪些|什么|哪家|哪[些家]|有没有|有没).*?(?:{_HOTEL_KEYWORDS})"),
    # "找一下上海的民宿" / "搜北京宾馆"
    re.compile(rf"(?:找[一]?下?|查[一]?下?|搜[一]?[下索]?).{{0,6}}(.{{2,6}}).*?(?:{_HOTEL_KEYWORDS})"),
    # "帮我找民宿" / "推荐酒店" / "看看宾馆"
    re.compile(rf"(?:帮我找|帮我查|搜索|推荐|[看瞧]看?).*?(?:{_HOTEL_KEYWORDS})"),
    # "住宿推荐" / "酒店搜索"
    re.compile(rf"(?:{_HOTEL_KEYWORDS}).*?(?:推荐|搜索|查询|在[哪那]|怎么样)"),
    # "XX附近有住宿吗" / "XX住宿" —— 收紧：必须含"附近/周边/旁边"或查询动词
    re.compile(rf"(.{{2,8}}?).*?(?:附近|周边|旁边).*?(?:{_HOTEL_KEYWORDS})"),
    # 删除原"倒装"和"住哪里"两条过宽模式（(.{2,8}?).*?(酒店|民宿|...) 与 (酒店|...).*?(.{2,8}?)）
    # 这两条是 BUG-008/009/010 的主因
]
```

对 `_RESTAURANT_PATTERNS`（87-110 行）和 `_SCENIC_PATTERNS`（113-136 行）做同样处理：
- 保留前 4 条带查询动词的正则
- 第 5 条"XX附近/周边"必须含"附近/周边/旁边"修饰
- **删除**最后几条无动词的倒装/泛化模式（如 `(?:住|住宿|...).*?(?:哪里|哪儿|...)` 之外的纯关键词匹配）

### 2.2 日期正则（BUG-011）

**根因**：`_TRAIN_PATTERNS` 中的日期提取正则（约 479 行）仅覆盖 `(明天|后天|今天|\d{1,2}月\d{1,2}[日号]|\d{4}-\d{1,2}-\d{1,2})`，"中秋节"等节假日无法解析。

**方案**：扩展日期正则并新增节假日映射表。在 `_TRAIN_PATTERNS` 之前新增：

```python
# 节假日名 → 日期映射（需定期更新，默认按当前年份推断）
_HOLIDAY_DATES = {
    "元旦": "01-01",
    "春节": "02-01",       # 农历，需动态计算，此处占位
    "清明": "04-05",
    "劳动节": "05-01",
    "端午": "06-01",       # 农历，占位
    "中秋": "09-15",       # 农历，占位
    "国庆": "10-01",
    "圣诞节": "12-25",
}

# 扩展日期捕获：下周X / 这周X / 月底 / 月初 / 节假日名
_DATE_PATTERN_EXTENDED = re.compile(
    r"(今天|明天|后天|大后天|"
    r"下[一二三四五六日天]|这[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}[日号]|"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"月底|月初|"
    r"元旦|春节|清明|劳动节|端午|中秋|国庆|圣诞节)"
)
```

然后将 `_TRAIN_PATTERNS` 中提取日期的代码（约 479 行）替换为：

```python
date_str = ""
date_match = _DATE_PATTERN_EXTENDED.search(q)
if date_match:
    date_str = date_match.group(1)
```

> ⚠️ **边界**：只改 `_TRAIN_PATTERNS` 内部的日期提取逻辑与新增模块常量，不改 `_TRAIN_PATTERNS` 的匹配模式本身（避免与文档 01 的差旅信号检测冲突）。

### 2.3 记忆查询误触发（BUG-018/019/020）

**根因**：`_MEMORY_PATTERNS`（201-207 行）含 `(我去过)` 等宽匹配，"去年去过北京今年还想去"被误识别。

**方案**：收紧 `_MEMORY_PATTERNS`，要求"去过/历史/记录"类词与"查询/查看/显示/汇总"等查询动词共现。

```python
_MEMORY_PATTERNS = [
    # 必须含查询动词 + 历史/记录类词
    re.compile(r"(查询?|看看?|查看|显示|汇总|总结)\s*(差旅|旅行|出行|旅游|行程|出差)\s*(记录|历史|情况|汇总|总结)"),
    # "我去过哪些地方" —— "去过" + 疑问词
    re.compile(r"我去过(?:哪些|哪里|什么地方|哪儿)"),
    # "查询我去过的地方" / "看看我的旅行记录"
    re.compile(r"(查询?|看看?|查看|显示).{0,6}(去过|旅行|差旅|出行|行程)"),
    # "历史/以往/过去" + "行程/旅行/差旅"
    re.compile(r"(历史|以往|过去|上次).{0,4}(行程|旅行|差旅|出行|记录)"),
    # "查/看 + 历史记录/出行记录/..."
    re.compile(r"(查|看|看看|显示|查看).{0,4}(历史记录|出行记录|行程记录|旅行记录|差旅记录|去过哪)"),
]
```

- 删除原 `(我去过|去过|去过哪些|去过哪里|去过什么地方)` 这条过宽模式（BUG-018 主因）
- 保留并强化"我去过哪些地方"（BUG-020 应命中）
- 新增"记得上次去XX的时候" → 不应命中 memory_query，应走 LLM（BUG-019 期望 fast_route_miss=true，本节收紧后自然 fall through）

### 2.4 翻译语言白名单（BUG-021/022/023/024）

**根因**：`_TRANSLATION_PATTERNS`（185-189 行）语言白名单仅含英/日/韩/法/德/中。

**方案**：扩展白名单。

```python
_TRANSLATION_PATTERNS = [
    re.compile(r"翻译[成用](英文|日文|韩文|法文|德文|中文|俄文|西班牙文|阿拉伯文|葡萄牙文|意大利文|泰文|越南文|"
               r"英语|日语|韩语|法语|德语|中文|俄语|西班牙语|阿拉伯语|葡萄牙语|意大利语|泰语|越南语)"),
    re.compile(r"用(英文|日文|韩文|法文|德文|中文|俄文|西班牙文|阿拉伯文|葡萄牙文|意大利文|泰文|越南文|"
               r"英语|日语|韩语|法语|德语|俄语|西班牙语|阿拉伯语|葡萄牙语|意大利语|泰语|越南语)怎么说"),
    re.compile(r"translate.*?to\s+(english|chinese|japanese|korean|french|german|"
               r"russian|spanish|arabic|portuguese|italian|thai|vietnamese)", re.I),
]
```

### 2.5 景点关键词误判差旅（BUG-031）

**根因**：`_SCENIC_KEYWORDS`（113-136 行）含"旅游/游玩"，"上海到杭州旅游"中的"旅游"被当作景点搜索信号。

**方案**：从 `_SCENIC_KEYWORDS` 中移除"旅游"（保留"游玩/逛逛/景点/景区"等），让差旅类查询走 LLM。同时在 `_SCENIC_PATTERNS` 中新增排除：含"X到/去/至/往 Y" + "旅游/出差/开会"的查询不匹配。

```python
# 从 _SCENIC_KEYWORDS 移除 "旅游"（差旅信号，应由 LLM 识别为 itinerary_planning）
_SCENIC_KEYWORDS = r"景点|景区|公园|乐园|好玩[的]?|游玩|逛逛|逛[一]?逛|必去|打卡|名胜|风景|出游|散心|观光|游览|踏青|登山|滑雪|漂流|徒步|看海|赏花|泡温泉|名胜古迹|网红[打]?卡|拍照[打]?卡"
# 注意：移除了 "旅游"
```

> ⚠️ 此修改与文档 01 的 `_TRIP_SIGNAL_PATTERNS`（含"旅游N天"）协同：纯"旅游"词移除后，"上海到杭州旅游"不再命中 scenic_search；差旅信号检测命中"旅游"（若加进 _TRIP_SIGNAL）则走 LLM。建议文档 01 的 `_TRIP_SIGNAL_PATTERNS` 也加入 `re.compile(r"旅游")` 兜底。**协调点**：本文档已在 2.5 移除"旅游"，文档 01 应在 `_TRIP_SIGNAL_PATTERNS` 加 `re.compile(r"旅游")`，两边不冲突（一个删词，一个加信号）。

## 验证

```bash
python tests/logic_audit/runner.py
```

期望（仅本文档修复后，假设文档 01/03/04/05/06 未修）：
- BUG-008/009/010 转为通过（fast_route_miss=true）
- BUG-011 转为通过（fast_route_miss=true，节假日走 LLM）
- BUG-018/019/020 转为通过
- BUG-021/022/023/024 转为通过（fast route 命中 translation）
- BUG-031 转为通过（fast_route_miss=true）
- 共减少 12 条 bug

### 注意副作用

收紧 `_HOTEL_PATTERNS` 等可能影响现有通过用例（如 CE-002 "上海有哪些酒店"、CE-005 "我想查杭州西湖附近的酒店"）。修复后请检查附录"通过用例"中 CE 系列仍为通过。若 CE-005 因删除倒装模式而 miss，需在 2.1 的正则中补回"XX附近/周边+酒店"的精确模式。

## 并行注意事项

- **文档 01** 新增 `_TRIP_SIGNAL_PATTERNS` 常量（约 208 行），本文档修改 `_MEMORY_PATTERNS`（201-207 行）和 `_TRANSLATION_PATTERNS`（185-189 行），区域相邻但不重叠。
- **文档 03** 修改 `_CITY_KEYWORDS`（210-214 行），本文档修改 `_MEMORY_PATTERNS`（201-207 行），不重叠。
- **文档 04** 修改 `_fast_match` 天气分支函数体，本文档只改模块常量，完全不冲突。
- 若 2.5 的"旅游"移除与文档 01 的 `_TRIP_SIGNAL_PATTERNS` 加"旅游"协同，需在合并后整体跑一次审计验证。

## 不做的事

- 不修改 `_fast_match` 函数体（边界归文档 01/04）
- 不修改 `_extract_currency`（未发现 bug）
- 不修改 `_resolve_elliptical`（归文档 03）
