# 修复文档 01：fast_route 差旅信号检测 + fast_event 提取

> **并行窗口专属文档** —— 本文档只修改 `agents/intention_agent.py` 的 `_fast_match` 顶部与新增模块级差旅信号常量。其他窗口同时修改同文件的其他区域，请勿越界。

## 修复范围

- **文件**：`agents/intention_agent.py`
- **修改区域**：
  - 新增模块级常量 `_TRIP_SIGNAL_PATTERNS`（建议放在 `_MEMORY_PATTERNS` 之后、`_CITY_KEYWORDS` 之前，约 208 行附近）
  - `_fast_match` 函数顶部（约 267-280 行），在现有记账分支之前新增差旅信号短路检测
- **禁止修改**（其他窗口负责）：
  - `_HOTEL_PATTERNS` / `_RESTAURANT_PATTERNS` / `_SCENIC_PATTERNS` / `_TRANSLATION_PATTERNS` / `_MEMORY_PATTERNS` / `_TRAIN_PATTERNS` 等模块级正则（→ 文档 02）
  - `_CITY_KEYWORDS` 与 `_resolve_elliptical`（→ 文档 03）
  - `_fast_match` 的天气分支（约 317-348 行，→ 文档 04）
  - `_fast_match` 其他 *_PATTERNS 分支体（酒店/餐厅/景点/汇率/翻译/火车票/记忆）

## 涉及 Bug

| Bug ID | 用例 ID | 类别 | 查询 |
|--------|---------|------|------|
| BUG-001 | FR-001 | fast_route_hijack | 明天从北京去上海出差3天，第一天下午要去上海大学开会… |
| BUG-002 | FR-002 | fast_route_hijack | 下周从广州去成都旅游5天，想住春熙路附近的酒店 |
| BUG-003 | FR-003 | fast_route_hijack | 帮我规划一下从北京到西安的3天行程，顺便帮我看看大雁塔附近的酒店 |
| BUG-004 | FR-004 | fast_route_hijack | 明天去杭州出差，会议结束后想去西湖玩，需要订个西湖边的民宿 |
| BUG-005 | FR-005 | fast_route_hijack | 周末从深圳去厦门3天2夜出差，第一天要去客户公司开会 |
| BUG-006 | FR-006 | fast_route_hijack | 下周三从上海飞北京出差2天，想看看故宫附近的酒店 |
| BUG-007 | FR-007 | fast_route_hijack | 安排一下从成都到丽江的4天旅游行程，想住束河古镇的客栈 |
| BUG-013 | EV-001 | event_extraction_loss | 明天从北京去上海出差3天 |
| BUG-014 | EV-002 | event_extraction_loss | 后天从广州去深圳出差1天 |
| BUG-015 | EV-003 | event_extraction_loss | 下个月去三亚旅游5天 |
| BUG-016 | EV-004 | event_extraction_loss | 下周从上海去北京探亲4天 |
| BUG-017 | EV-005 | event_extraction_loss | 明天去杭州开会 |

共 12 条。两类 bug 同根因：fast route 命中单关键词后跳过 LLM，既吞掉多意图又丢 fast_event。修复策略统一为"差旅信号短路 → return None 走 LLM"。

## 根因

`agents/intention_agent.py:267` `_fast_match` 在 `dialogue_history=[]` 时只要任一 *_PATTERNS 命中就返回，没有差旅信号前置检测。差旅查询（出差/旅游/探亲 + 天数/开会/行程）应优先走 LLM 路径，由 LLM 生成 `fast_event` 与多意图 `agent_schedule`。

## 修复方案

### 步骤 1：新增模块级差旅信号常量

在 `_MEMORY_PATTERNS`（约 201-207 行）之后、`_CITY_KEYWORDS`（约 210 行）之前插入：

```python
# ── 差旅信号检测（用于 fast route 顶部短路，强制走 LLM） ──
# 命中任一即视为差旅/行程规划场景，不进 fast route
_TRIP_SIGNAL_PATTERNS = [
    re.compile(r"出差"),                    # 明确出差
    re.compile(r"\d+\s*天[的行程]?"),       # "3天" / "3天的行程" / "3天行程"
    re.compile(r"\d+\s*[日天][以之内]?[前后上]"),  # "3天以内" / "3天上"
    re.compile(r"[开见谈]会"),              # 开会/见客户/谈判
    re.compile(r"行程"),                    # 行程规划
    re.compile(r"安排[一二三四五六七八九两]?\s*[天下周]"),  # 安排一下/安排三天
    re.compile(r"规划[一行]?下?"),          # 规划/规划一下/规划行程
    re.compile(r"攻略"),                    # 旅游攻略
    re.compile(r"旅游\d+\s*天"),            # 旅游5天
    re.compile(r"探亲"),
    re.compile(r"度[假蜜月]"),              # 度假/度蜜月
]

def _has_trip_signal(query: str) -> bool:
    """检测查询是否含差旅/行程规划信号。"""
    return any(p.search(query) for p in _TRIP_SIGNAL_PATTERNS)
```

### 步骤 2：在 `_fast_match` 顶部新增短路检测

定位 `_fast_match` 函数（约 267 行起），在 `_has_history = bool(dialogue_history)` 之后、记账分支之前插入：

```python
def _fast_match(query: str, dialogue_history: list = None) -> Optional[dict]:
    """
    规则快速路由器：...
    """
    _has_history = bool(dialogue_history)
    q = query.strip()

    # ── 差旅信号短路：含出差/行程/开会等信号强制走 LLM ──
    # 原因：fast route 命中单关键词（如'酒店'）会吞掉 itinerary_planning
    # 意图并丢失 fast_event，导致差旅信息无法写入长期记忆。
    if _has_trip_signal(q):
        return None

    # 记账
    _CATEGORY_MAP = { ... }
    ...
```

## 验证

修复后跑审计：

```bash
python tests/logic_audit/runner.py
```

期望结果：
- BUG-001~007、BUG-013~017 共 12 条转为通过（`fast_route_miss=true`，由 LLM 兜底）
- 总 bug 数从 33 降至 21
- 不应引入新的 bug（其他用例不受影响）

### 手工抽检

```bash
python -c "
from agents.intention_agent import _fast_match
queries = [
    '明天从北京去上海出差3天',
    '帮我规划一下从北京到西安的3天行程',
    '明天去杭州开会',
    '下个月去三亚旅游5天',
]
for q in queries:
    r = _fast_match(q, [])
    print(f'{q[:30]:32} -> {\"LLM\" if r is None else \"fast:\" + str(r[\"agent_schedule\"])}')
"
```

期望全部输出 `LLM`。

## 并行注意事项

- **文档 02** 修改 `_MEMORY_PATTERNS` 等模块常量，与本文档新增的 `_TRIP_SIGNAL_PATTERNS` 不在同一区域，git 行级合并不冲突。
- **文档 03** 修改 `_CITY_KEYWORDS`（210-214 行）与 `_resolve_elliptical`，本文档新增常量建议放在 208 行附近，紧邻但不重叠。
- **文档 04** 修改 `_fast_match` 天气分支（317-348 行），本文档修改 `_fast_match` 顶部（267-282 行），两者相距 35 行以上，不冲突。
- 若 git 合并出现冲突，优先保留各文档新增的逻辑，再手动合并 import 与常量声明顺序。

## 不做的事

- 不在 fast route 内生成 `fast_event`（交给 LLM 路径生成，更准确）
- 不修改 LLM prompt（不在本审计范围）
- 不动 `_resolve_elliptical`（即使差旅信号命中，省略追问仍走原逻辑）
