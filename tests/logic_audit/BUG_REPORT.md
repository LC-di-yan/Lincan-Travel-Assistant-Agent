# 逻辑审计 Bug 报告

- 生成时间：2026-07-30 22:06:54
- 总用例：85
- 发现 bug：0
- 审计范围：`agents/intention_agent.py` 的 `_fast_match` / `_resolve_elliptical` / `_extract_currency`，以及 `.claude/skills/place-search/script/agent.py` 的纯方法
- 审计方式：仅静态分析，不调 LLM、不调外部 API

## 按类别统计

| 类别 | bug 数 |
|------|--------|

## Bug 列表

## 附录：通过用例

| ID | 类别 | 查询 |
|----|------|------|
| FR-001 | fast_route_hijack | 明天从北京去上海出差3天，第一天下午要去上海大学开会，第二天早上想去上海大学附近... |
| FR-002 | fast_route_hijack | 下周从广州去成都旅游5天，想住春熙路附近的酒店 |
| FR-003 | fast_route_hijack | 帮我规划一下从北京到西安的3天行程，顺便帮我看看大雁塔附近的酒店 |
| FR-004 | fast_route_hijack | 明天去杭州出差，会议结束后想去西湖玩，需要订个西湖边的民宿 |
| FR-005 | fast_route_hijack | 周末从深圳去厦门3天2夜出差，第一天要去客户公司开会 |
| FR-006 | fast_route_hijack | 下周三从上海飞北京出差2天，想看看故宫附近的酒店 |
| FR-007 | fast_route_hijack | 安排一下从成都到丽江的4天旅游行程，想住束河古镇的客栈 |
| CE-001 | city_extraction | 从北京去上海出差3天 |
| CE-002 | city_extraction | 上海有哪些酒店 |
| CE-003 | city_extraction | 北京到广州的火车票 |
| CE-004 | city_extraction | 广州到北京到上海的火车票 |
| CE-005 | city_extraction | 我想查杭州西湖附近的酒店 |
| CE-006 | city_extraction | 虹桥火车站附近的酒店 |
| KB-001 | keyword_too_broad | 我住在北京朝阳区 |
| KB-002 | keyword_too_broad | 今天玩得很开心 |
| KB-003 | keyword_too_broad | 他住的地方离公司很远 |
| KB-004 | keyword_too_broad | 昨晚吃了一顿大餐 |
| KB-005 | keyword_too_broad | 我们去逛逛街吧 |
| KB-006 | keyword_too_broad | 公司在哪个楼层 |
| DT-001 | date_extraction_gap | 下周三从北京到上海出差 |
| DT-002 | date_extraction_gap | 月底去广州出差 |
| DT-003 | date_extraction_gap | 中秋节去杭州旅游 |
| DT-004 | date_extraction_gap | 12月25日从北京去三亚 |
| DT-005 | date_extraction_gap | 下周一到下周三去深圳出差 |
| EL-001 | elliptical_limit | 那虹桥呢 |
| EL-002 | elliptical_limit | 那大学城呢 |
| EL-003 | elliptical_limit | 那香格里拉呢 |
| EL-004 | elliptical_limit | 那浦东新区呢 |
| EL-005 | elliptical_limit | 那嘉兴呢 |
| PS-001 | place_type_suppression | 酒店附近有什么好吃的 |
| PS-002 | place_type_suppression | 民宿周边有什么景点 |
| PS-003 | place_type_suppression | 宾馆楼下有什么好吃的餐厅 |
| PS-004 | place_type_suppression | 客栈对面的火锅店 |
| PS-005 | place_type_suppression | 住的地方附近有什么好玩的 |
| PS-006 | place_type_suppression | 酒店附近有哪些公园可以逛逛 |
| EV-001 | event_extraction_loss | 明天从北京去上海出差3天 |
| EV-002 | event_extraction_loss | 后天从广州去深圳出差1天 |
| EV-003 | event_extraction_loss | 下个月去三亚旅游5天 |
| EV-004 | event_extraction_loss | 下周从上海去北京探亲4天 |
| EV-005 | event_extraction_loss | 明天去杭州开会 |
| CA-001 | currency_ambiguity | 打车花了100元 |
| CA-002 | currency_ambiguity | 100元打车的发票 |
| CA-003 | currency_ambiguity | 酒店一晚500元 |
| CA-004 | currency_ambiguity | 100美元换人民币 |
| CA-005 | currency_ambiguity | 日元汇率怎么样 |
| MF-001 | memory_false_trigger | 我想去北京 |
| MF-002 | memory_false_trigger | 我去过北京吗 |
| MF-003 | memory_false_trigger | 去年去过北京，今年还想去 |
| MF-004 | memory_false_trigger | 记得上次去北京的时候 |
| MF-005 | memory_false_trigger | 我去过哪些地方旅游 |
| TL-001 | translation_lang_gap | 翻译成俄语 |
| TL-002 | translation_lang_gap | 用阿拉伯语怎么说 |
| TL-003 | translation_lang_gap | 翻译成西班牙语 |
| TL-004 | translation_lang_gap | 翻译成英文 |
| TL-005 | translation_lang_gap | translate to Russian |
| LC-001 | location_context_over_extract | 上海大学附近的酒店 |
| LC-002 | location_context_over_extract | 北京大学周边的民宿 |
| LC-003 | location_context_over_extract | 复旦大学邯郸校区附近酒店 |
| LC-004 | location_context_over_extract | 中关村地铁站附近的酒店 |
| LC-005 | location_context_over_extract | 外滩附近的酒店 |
| MI-001 | multi_intent_collapse | 查一下北京的天气和上海的酒店 |
| MI-002 | multi_intent_collapse | 广州天气和美食 |
| MI-003 | multi_intent_collapse | 北京景点和酒店 |
| MI-004 | multi_intent_collapse | 杭州天气和景点和美食 |
| MI-005 | multi_intent_collapse | 查上海天气顺便搜一下外滩附近的酒店 |
| TT-001 | train_ticket_ambiguity | 北京去上海玩 |
| TT-002 | train_ticket_ambiguity | 从广州到深圳出差 |
| TT-003 | train_ticket_ambiguity | 上海到杭州旅游 |
| TT-004 | train_ticket_ambiguity | 帮我查火车票广州到深圳 |
| TT-005 | train_ticket_ambiguity | 明天从北京到上海出差3天 |
| WM-001 | weather_mixed_query | 查北京天气和上海酒店 |
| WM-002 | weather_mixed_query | 上海天气和北京天气 |
| WM-003 | weather_mixed_query | 杭州天气和杭州酒店 |
| WM-004 | weather_mixed_query | 查一下上海天气，然后帮我搜北京的酒店 |
| RL-001 | restaurant_in_lodging_context | 酒店附近有什么好吃的 |
| RL-002 | restaurant_in_lodging_context | 民宿周边的火锅店 |
| RL-003 | restaurant_in_lodging_context | 住的地方附近有什么特色菜 |
| RL-004 | restaurant_in_lodging_context | 酒店里的餐厅 |
| RL-005 | restaurant_in_lodging_context | 酒店早餐 |
| CR-001 | context_resolution | 请帮我查询具体的汉庭酒店房型和价格 |
| CR-002 | context_resolution | 帮我查一下全季的房型 |
| CR-003 | context_resolution | 有什么好吃的推荐 |
| CR-004 | context_resolution | 有哪些景点可以逛 |
| CR-005 | context_resolution | 请帮我查询具体的汉庭酒店房型和价格 |
| CR-006 | context_resolution | 附近有哪些酒店和餐厅 |

---
*本报告由 `tests/logic_audit/runner.py` 自动生成，审计逻辑详见 `tests/logic_audit/README.md`*