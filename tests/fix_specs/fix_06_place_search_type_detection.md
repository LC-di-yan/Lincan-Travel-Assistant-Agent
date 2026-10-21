# 修复文档 06：place-search 类型识别压制修复

> **并行窗口专属文档** —— 本文档只修改 `.claude/skills/place-search/script/agent.py` 的 `_is_restaurant_query` 与 `_is_scenic_query`。其他窗口同时修改同文件的其他函数，请勿越界。

## 修复范围

- **文件**：`.claude/skills/place-search/script/agent.py`
- **修改区域**：
  - `_NON_RESTAURANT_KEYWORDS`（约 75-78 行，仅扩展不删）
  - `_NON_SCENIC_KEYWORDS`（约 94-97 行，仅扩展不删）
  - `_is_restaurant_query` 方法（约 205-224 行）
  - `_is_scenic_query` 方法（约 349-364 行）
- **禁止修改**（其他窗口负责）：
  - `_extract_city` / `_extract_location_context`（→ 文档 05）
  - `_COMMON_CITIES` / `_UNIVERSITY_CITY_MAP`
  - `_extract_food_params` / `_extract_scenic_params` / `_extract_search_params`
  - `_hotel_search` / `_restaurant_search` / `_scenic_search` 等 API 调用方法
  - `_build_result` / `_build_restaurant_result` / `_build_scenic_result`
  - `reply` 主流程

## 涉及 Bug

| Bug ID | 用例 ID | 类别 | 查询 | 期望 place_type |
|--------|---------|------|------|----------------|
| BUG-032 | RL-004 | restaurant_in_lodging_context | 酒店里的餐厅 | 餐厅搜索 |
| BUG-033 | RL-005 | restaurant_in_lodging_context | 酒店早餐 | 餐厅搜索 |

共 2 条。

> **注意**：PS-001~006（place_type_suppression 类别）当前是通过用例，期望 `place_type` 分别为餐厅/景点。但实际行为见审计报告附录——PS-001 "酒店附近有什么好吃的" 实际是酒店搜索（被压制），用例期望是餐厅搜索。**这些用例实际是 bug，但 runner 未报**，因为用例的 `expected.place_type` 与 `_fast_match` 路由结果联动校验。本文档修复后需复核 PS 系列用例。

## 根因

`.claude/skills/place-search/script/agent.py:205-224` `_is_restaurant_query` 中 `_NON_RESTAURANT_KEYWORDS` 前置排除，after_kw 检查只识别"附近/周边/旁边/楼下/对面"：

```python
def _is_restaurant_query(self, query: str) -> bool:
    q = (query or "").strip()
    for kw in _NON_RESTAURANT_KEYWORDS:
        if kw in q:
            after_kw = q[q.index(kw) + len(kw):]
            if any(rk in after_kw for rk in ["附近", "周边", "旁边", "楼下", "对面"]):
                continue
            before_kw = q[:q.index(kw)]
            if any(rk in before_kw for rk in _RESTAURANT_KEYWORDS):
                continue
            return False
    for kw in _RESTAURANT_KEYWORDS:
        if kw in q:
            return True
    return False
```

- "酒店里的餐厅"：after_kw="里的餐厅"，不含"附近/周边/..."，before_kw="" 无餐厅词 → 返回 False（BUG-032）
- "酒店早餐"：after_kw="早餐"，"早餐"在 `_RESTAURANT_KEYWORDS` 但 after_kw 检查只看修饰词不看餐厅词本身 → 返回 False（BUG-033）

## 修复方案

### 步骤 1：扩展 `_is_restaurant_query` 的 after_kw 检查

将 `_is_restaurant_query`（约 205-224 行）改为：

```python
    def _is_restaurant_query(self, query: str) -> bool:
        """判断查询是否为餐厅/美食搜索。非餐饮关键词优先（避免"XX酒店附近的美食"误判）。"""
        q = (query or "").strip()
        # 非餐饮关键词优先检查
        for kw in _NON_RESTAURANT_KEYWORDS:
            if kw in q:
                idx = q.index(kw)
                after_kw = q[idx + len(kw):]
                before_kw = q[:idx]
                # 1. after_kw 含位置修饰词 → 仍是餐厅查询（"酒店附近的美食"）
                if any(rk in after_kw for rk in ["附近", "周边", "旁边", "楼下", "对面", "里", "里的", "里面", "内", "中"]):
                    continue
                # 2. after_kw 本身含餐厅词 → 是餐厅查询（"酒店里的餐厅"、"酒店早餐"）
                if any(rk in after_kw for rk in _RESTAURANT_KEYWORDS):
                    continue
                # 3. before_kw 含餐厅词 → 是餐厅查询（"火锅店在酒店旁"）
                if any(rk in before_kw for rk in _RESTAURANT_KEYWORDS):
                    continue
                return False
        # 检查餐饮关键词
        for kw in _RESTAURANT_KEYWORDS:
            if kw in q:
                return True
        return False
```

关键变更：
- 新增 after_kw 中"里/里的/里面/内/中"等修饰词检查（覆盖"酒店里的餐厅"）
- 新增 after_kw 中餐厅词直接检查（覆盖"酒店早餐"——"早餐"在 `_RESTAURANT_KEYWORDS`）

### 步骤 2：同步修复 `_is_scenic_query`

`_is_scenic_query`（约 349-364 行）有同样问题，同步修复：

```python
    def _is_scenic_query(self, query: str) -> bool:
        """判断查询是否为景点/旅游搜索。"""
        q = (query or "").strip()
        for kw in _NON_SCENIC_KEYWORDS:
            if kw in q:
                idx = q.index(kw)
                after = q[idx + len(kw):]
                before = q[:idx]
                if any(rk in after for rk in ["附近", "周边", "旁边", "楼下", "对面", "里", "里的", "里面", "内", "中"]):
                    continue
                if any(rk in after for rk in _SCENIC_KEYWORDS):
                    continue
                if any(rk in before for rk in _SCENIC_KEYWORDS):
                    continue
                return False
        for kw in _SCENIC_KEYWORDS:
            if kw in q:
                return True
        return False
```

### 步骤 3：复核 PS 系列用例

修复后跑审计，关注 `06_place_type_suppression.json` 中 PS-001~006：

| 用例 | 查询 | 原期望 | 修复后实际 | 是否需更新用例 |
|------|------|--------|-----------|---------------|
| PS-001 | 酒店附近有什么好吃的 | 餐厅搜索 | 餐厅搜索（after_kw="附近有什么好吃的"含"附近"→continue→检查餐厅词"好吃的"→True） | 通过，无需更新 |
| PS-002 | 民宿周边有什么景点 | 景点搜索 | 景点搜索（after_kw="周边有什么景点"含"周边"→continue→检查景点词"景点"→True） | 通过 |
| PS-003 | 宾馆楼下有什么好吃的餐厅 | 餐厅搜索 | 餐厅搜索（after_kw="楼下有什么好吃的餐厅"含"楼下"→continue→"餐厅"→True） | 通过 |
| PS-004 | 客栈对面的火锅店 | 餐厅搜索 | 餐厅搜索（after_kw="对面的火锅店"含"对面"→continue→"火锅"→True） | 通过 |
| PS-005 | 住的地方附近有什么好玩的 | 景点搜索 | 景点搜索（"住的地方"含"住的地方"→after_kw="附近有什么好玩的"含"附近"→continue→"好玩"→True） | 通过 |
| PS-006 | 酒店附近有哪些公园可以逛逛 | 景点搜索 | 景点搜索（after_kw="附近有哪些公园可以逛逛"含"附近"→continue→"公园"→True） | 通过 |

预计 PS 系列修复后全部通过（原本因 runner 联动校验逻辑未报 bug，但实际 `_is_restaurant_query("酒店附近有什么好吃的")` 修复前返回 True 因 after_kw 含"附近"→continue→"好吃的"在 `_RESTAURANT_KEYWORDS`→True。所以 PS-001 原本就通过）。

> ⚠️ **复核结论**：PS 系列原本通过，修复后仍通过。RL-004/005（BUG-032/033）是新增覆盖场景，修复后转为通过。

## 验证

```bash
python tests/logic_audit/runner.py
```

期望：
- BUG-032（RL-004 "酒店里的餐厅"）：place_type=餐厅搜索 → 通过
- BUG-033（RL-005 "酒店早餐"）：place_type=餐厅搜索 → 通过
- PS-001~006 仍通过

### 手工抽检

```bash
python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('psa', '.claude/skills/place-search/script/agent.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
a = m.PlaceSearchAgent()
cases = [
    '酒店里的餐厅',
    '酒店早餐',
    '酒店附近有什么好吃的',
    '民宿周边的火锅店',
    '酒店',  # 纯酒店，应返回 False
    '上海大学附近的酒店',  # 纯酒店，应返回 False
]
for q in cases:
    print(f'{q:25} is_restaurant={a._is_restaurant_query(q)}')
"
```

期望：
- `酒店里的餐厅` is_restaurant=True
- `酒店早餐` is_restaurant=True
- `酒店附近有什么好吃的` is_restaurant=True
- `民宿周边的火锅店` is_restaurant=True
- `酒店` is_restaurant=False
- `上海大学附近的酒店` is_restaurant=False

## 并行注意事项

- **文档 05** 修改 `_extract_city`（471-477 行）和 `_extract_location_context`（481-526 行），本文档修改 `_is_restaurant_query`（205-224 行）和 `_is_scenic_query`（349-364 行），区域相距 200+ 行，不冲突。
- **文档 02** 修改 `intention_agent.py` 的 `_SCENIC_KEYWORDS`，本文档修改 `place-search/script/agent.py` 的 `_NON_*_KEYWORDS`，不同文件，不冲突。但若文档 02 从 `_SCENIC_KEYWORDS` 移除"旅游"，本文档 `_is_scenic_query` 中 `any(rk in after for rk in _SCENIC_KEYWORDS)` 的行为会同步变化，属期望协同。
- **文档 01/03/04** 修改 `intention_agent.py`，本文档修改 `place-search/script/agent.py`，不冲突。

## 不做的事

- 不修改 `_extract_city` / `_extract_location_context`（→ 文档 05）
- 不修改 `_RESTAURANT_KEYWORDS` / `_SCENIC_KEYWORDS` 本身（关键词集归模块所有，本节只改 `_NON_*` 与判定逻辑）
- 不修改 API 调用方法
- 不修改 `reply` 主流程
