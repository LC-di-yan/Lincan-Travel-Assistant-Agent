# 逻辑审计（Logic Audit）

本目录用于对 `IntentionAgent` 与 `PlaceSearchAgent` 的**纯逻辑分支**进行静态审计，
不依赖 LLM、不依赖外部 API（高德 / 12306 / 汇率等），仅靠正则匹配器与提取器
跑出实际行为，再与人工语义分析的期望行为对比，自动产出 `BUG_REPORT.md`。

## 运行

在项目根目录执行：

```bash
python tests/logic_audit/runner.py
```

运行后会在 `tests/logic_audit/BUG_REPORT.md` 生成（或覆盖）bug 清单。

## 用例格式

每条用例为 JSON 对象，置于 `cases/*.json`，可选字段标注为 `[可选]`：

```json
{
  "id": "FR-001",
  "category": "fast_route_hijack",
  "query": "明天从北京去上海出差3天",
  "dialogue": ["用户: ...", "助手: ..."],
  "expected": {
    "intents": ["itinerary_planning"],
    "agents": ["itinerary_planning"],
    "fast_event": {"origin": "北京", "destination": "上海"},
    "needs_clarification": false,
    "clarification_question": "",
    "place_type": "酒店搜索",
    "place_city": "上海",
    "place_keywords_contains": "上海大学",
    "currency": null,
    "agent_count_min": 2
  },
  "note": "核心意图是出差行程规划，不应被酒店关键词劫持"
}
```

`expected` 字段全部可选，runner 只校验出现的字段。

## Bug 类别

| # | 类别 | 说明 |
|---|------|------|
| 1 | `fast_route_hijack` | 快速路由用单关键词劫持多意图查询，吞掉 itinerary_planning / fast_event |
| 2 | `city_extraction` | 多城市 / 出发地 / 目的地错配 |
| 3 | `keyword_too_broad` | 关键词过宽误命中（"住"、"玩"等单字误触发） |
| 4 | `date_extraction_gap` | 日期关键词覆盖不全（下周X / 月底 / 节假日名） |
| 5 | `elliptical_limit` | 省略追问仅识别预定义城市集 |
| 6 | `place_type_suppression` | PlaceSearchAgent 用 `_NON_*` 把真实意图压制为酒店 |
| 7 | `event_extraction_loss` | fast route 路径跳过 LLM 导致 fast_event 不生成 |
| 8 | `currency_ambiguity` | 含金额的查询误触发汇率 |
| 9 | `memory_false_trigger` | "去过"等关键词在非历史查询场景误触发 |
| 10 | `translation_lang_gap` | 翻译语言名不在白名单（如"俄语"、"阿拉伯语"） |
| 11 | `location_context_over_extract` | `_extract_location_context` 把地标当行政词提取 |
| 12 | `multi_intent_collapse` | 多意图查询只保留 priority 最低那个 |
| 13 | `train_ticket_ambiguity` | "A 去 B 玩"被误判为火车票查询 |
| 14 | `weather_mixed_query` | "查A天气和B酒店" 城市错配 |
| 15 | `restaurant_in_lodging_context` | "酒店附近美食" 被住宿压制 |

## 限制

- runner 仅调用 `agents.intention_agent._fast_match` / `_resolve_elliptical` /
  `_extract_currency` 以及 `PlaceSearchAgent` 的纯方法，**不调用 LLM**。
- LLM 路径的 bug（如 prompt 模板缺陷）不在覆盖范围内。
- 用例中的 `expected` 由人工语义分析得出，可能仍有疏漏，发现后请补 case。
