"""
逻辑审计运行器（静态分析）

只调用项目内的纯函数/方法，不调 LLM、不调外部 API：
- agents.intention_agent._fast_match
- agents.intention_agent._resolve_elliptical
- agents.intention_agent._extract_currency
- .claude/skills/place-search/script/agent.py: PlaceSearchAgent 的纯方法
  (_is_restaurant_query / _is_scenic_query / _extract_city /
   _extract_search_params / _extract_food_params / _extract_scenic_params)

运行：python tests/logic_audit/runner.py
输出：tests/logic_audit/BUG_REPORT.md
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 让脚本能从项目根目录导入
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from agents.intention_agent import (  # noqa: E402
    _extract_currency,
    _fast_match,
    _resolve_elliptical,
)

# ── 加载 PlaceSearchAgent（位于 .claude/skills，非标准包路径） ──
_PSA_PATH = PROJECT_ROOT / ".claude" / "skills" / "place-search" / "script" / "agent.py"
_spec = importlib.util.spec_from_file_location("_psa_audit", _PSA_PATH)
_psa_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_psa_mod)
PlaceSearchAgent = _psa_mod.PlaceSearchAgent

CASES_DIR = Path(__file__).parent / "cases"
REPORT_PATH = Path(__file__).parent / "BUG_REPORT.md"


def _agents_of(match: dict | None) -> list[str]:
    if not match:
        return []
    return [t.get("agent_name", "") for t in match.get("agent_schedule", [])]


def _intents_of(match: dict | None) -> list[str]:
    if not match:
        return []
    return [i.get("type", "") for i in match.get("intents", [])]


def _run_intention(query: str, dialogue: list[str] | None) -> dict | None:
    """先尝试省略追问，再快速路由。返回 None 表示两者都未命中。"""
    if dialogue:
        ell = _resolve_elliptical(query, dialogue)
        if ell is not None:
            return {"path": "elliptical", "match": ell}
    fast = _fast_match(query, dialogue_history=dialogue or [])
    if fast is not None:
        return {"path": "fast", "match": fast}
    return None


def _run_place_search(query: str) -> dict[str, Any]:
    """模拟 PlaceSearchAgent.reply 的纯逻辑分支，不调 API。"""
    agent = PlaceSearchAgent()
    is_restaurant = agent._is_restaurant_query(query)
    is_scenic = not is_restaurant and agent._is_scenic_query(query)
    if is_restaurant:
        place_type = "餐厅搜索"
    elif is_scenic:
        place_type = "景点搜索"
    else:
        place_type = "酒店搜索"
    city = agent._extract_city(query)
    if not city:
        return {
            "place_type": place_type,
            "place_city": "",
            "place_keywords": "",
        }
    if is_restaurant:
        params = agent._extract_food_params(query, city)
    elif is_scenic:
        params = agent._extract_scenic_params(query, city)
    else:
        params = agent._extract_search_params(query, city)
    return {
        "place_type": place_type,
        "place_city": city,
        "place_keywords": params.get("keywords", ""),
    }


def _run_currency(query: str) -> dict | None:
    return _extract_currency(query)


# ── 期望字段校验器 ──

def _check_case(case: dict) -> dict:
    """返回 {actual, mismatches: [str, ...]}"""
    query = case["query"]
    dialogue = case.get("dialogue")
    expected = case.get("expected", {})

    actual: dict[str, Any] = {}
    mismatches: list[str] = []

    # 路由结果
    route = _run_intention(query, dialogue)
    if route is None:
        actual["fast_route_miss"] = True
        actual["agents"] = []
        actual["intents"] = []
        actual["fast_event"] = {}
        actual["needs_clarification"] = None
    else:
        actual["fast_route_miss"] = False
        actual["route_path"] = route["path"]
        m = route["match"]
        actual["agents"] = _agents_of(m)
        actual["intents"] = _intents_of(m)
        actual["fast_event"] = m.get("fast_event", {}) or {}
        actual["needs_clarification"] = m.get("needs_clarification")
        actual["key_entities"] = m.get("key_entities", {}) or {}

    # 货币（仅当查询里有可能的货币信号或 expected 含 currency 字段）
    if "currency_extracted" in expected or "汇率" in query or any(
        w in query for w in ["美元", "人民币", "日元", "欧元", "英镑", "港币", "韩元"]
    ):
        actual["currency_extracted"] = _run_currency(query)

    # PlaceSearch 行为（当路由到 hotel/restaurant/scenic，或 expected 含 place_* 字段）
    place_agents = {"hotel_search", "restaurant_search", "scenic_search"}
    route_hit_place = bool(set(actual["agents"]) & place_agents)
    expected_has_place = any(k.startswith("place_") for k in expected)
    if route_hit_place or expected_has_place:
        ps = _run_place_search(query)
        actual.update(ps)

    # ── 字段对比 ──
    # agents
    if "agents" in expected:
        if sorted(actual["agents"]) != sorted(expected["agents"]):
            mismatches.append(
                f"agents 期望={expected['agents']} 实际={actual['agents']}"
            )
    if "agents_contains" in expected:
        missing = [a for a in expected["agents_contains"] if a not in actual["agents"]]
        if missing:
            mismatches.append(f"agents 缺少 {missing}，实际={actual['agents']}")
    if "agent_count_min" in expected:
        if len(actual["agents"]) < expected["agent_count_min"]:
            mismatches.append(
                f"agent 数量期望>={expected['agent_count_min']} 实际={len(actual['agents'])}"
            )
    if "fast_route_miss" in expected:
        if actual["fast_route_miss"] != expected["fast_route_miss"]:
            mismatches.append(
                f"fast_route_miss 期望={expected['fast_route_miss']} "
                f"实际={actual['fast_route_miss']}"
            )
    if "elliptical_resolved" in expected:
        resolved = actual.get("route_path") == "elliptical"
        if resolved != expected["elliptical_resolved"]:
            mismatches.append(
                f"elliptical_resolved 期望={expected['elliptical_resolved']} "
                f"实际={resolved}"
            )
    if "fast_event_present" in expected:
        present = bool(actual["fast_event"])
        if present != expected["fast_event_present"]:
            mismatches.append(
                f"fast_event 存在 期望={expected['fast_event_present']} 实际={present}"
            )
    if "fast_event_has_destination" in expected:
        has = bool(actual["fast_event"].get("destination"))
        exp = expected["fast_event_has_destination"]
        # 当 expected 是字符串时同时校验值
        if isinstance(exp, str):
            if actual["fast_event"].get("destination") != exp:
                mismatches.append(
                    f"fast_event.destination 期望={exp} "
                    f"实际={actual['fast_event'].get('destination')}"
                )
        elif has != exp:
            mismatches.append(f"fast_event.destination 存在 期望={exp} 实际={has}")
    if "fast_event_has_origin" in expected:
        has = bool(actual["fast_event"].get("origin"))
        exp = expected["fast_event_has_origin"]
        if isinstance(exp, str):
            if actual["fast_event"].get("origin") != exp:
                mismatches.append(
                    f"fast_event.origin 期望={exp} "
                    f"实际={actual['fast_event'].get('origin')}"
                )
        elif has != exp:
            mismatches.append(f"fast_event.origin 存在 期望={exp} 实际={has}")
    if "fast_event_destination" in expected:
        if actual["fast_event"].get("destination") != expected["fast_event_destination"]:
            mismatches.append(
                f"fast_event.destination 期望={expected['fast_event_destination']} "
                f"实际={actual['fast_event'].get('destination')}"
            )
    if "fast_event_origin" in expected:
        if actual["fast_event"].get("origin") != expected["fast_event_origin"]:
            mismatches.append(
                f"fast_event.origin 期望={expected['fast_event_origin']} "
                f"实际={actual['fast_event'].get('origin')}"
            )
    if "fast_event_trip_purpose" in expected:
        if actual["fast_event"].get("trip_purpose") != expected["fast_event_trip_purpose"]:
            mismatches.append(
                f"fast_event.trip_purpose 期望={expected['fast_event_trip_purpose']} "
                f"实际={actual['fast_event'].get('trip_purpose')}"
            )
    if "needs_clarification" in expected:
        if actual["needs_clarification"] != expected["needs_clarification"]:
            mismatches.append(
                f"needs_clarification 期望={expected['needs_clarification']} "
                f"实际={actual['needs_clarification']}"
            )
    if "key_entities_destination" in expected:
        if actual["key_entities"].get("destination") != expected["key_entities_destination"]:
            mismatches.append(
                f"key_entities.destination 期望={expected['key_entities_destination']} "
                f"实际={actual['key_entities'].get('destination')}"
            )
    if expected.get("needs_clarification_not_true"):
        if actual["needs_clarification"] is True:
            mismatches.append(
                f"needs_clarification 不应为 True（实际反问了用户），"
                f"实际={actual['needs_clarification']}"
            )
    if "key_entities_origin" in expected:
        if actual["key_entities"].get("origin") != expected["key_entities_origin"]:
            mismatches.append(
                f"key_entities.origin 期望={expected['key_entities_origin']} "
                f"实际={actual['key_entities'].get('origin')}"
            )
    if "currency_extracted" in expected:
        exp = expected["currency_extracted"]
        act = actual.get("currency_extracted")
        if exp is None and act is not None:
            mismatches.append(f"currency 期望不触发 实际={act}")
        elif exp is not None and act != exp:
            mismatches.append(f"currency 期望={exp} 实际={act}")
    if "place_type" in expected:
        if actual.get("place_type") != expected["place_type"]:
            mismatches.append(
                f"place_type 期望={expected['place_type']} "
                f"实际={actual.get('place_type')}"
            )
    if "place_city" in expected:
        if actual.get("place_city") != expected["place_city"]:
            mismatches.append(
                f"place_city 期望={expected['place_city']} "
                f"实际={actual.get('place_city')}"
            )
    if "place_keywords_contains" in expected:
        kw = actual.get("place_keywords", "")
        if expected["place_keywords_contains"] not in kw:
            mismatches.append(
                f"place_keywords 期望包含'{expected['place_keywords_contains']}' "
                f"实际='{kw}'"
            )

    return {"actual": actual, "mismatches": mismatches}


# ── Bug 报告生成 ──

_CATEGORY_LABEL = {
    "fast_route_hijack": "快速路由劫持多意图",
    "city_extraction": "城市提取错配",
    "keyword_too_broad": "关键词过宽误命中",
    "date_extraction_gap": "日期关键词覆盖不全",
    "elliptical_limit": "省略追问仅识别预定义城市",
    "place_type_suppression": "PlaceSearch 类型压制",
    "event_extraction_loss": "行程要素提取丢失",
    "currency_ambiguity": "货币提取歧义",
    "memory_false_trigger": "记忆查询误触发",
    "translation_lang_gap": "翻译语言白名单不全",
    "location_context_over_extract": "位置限定过度提取",
    "multi_intent_collapse": "多意图塌缩为单意图",
    "train_ticket_ambiguity": "火车票正则误判",
    "weather_mixed_query": "天气混合查询城市错配",
    "restaurant_in_lodging_context": "住宿上下文压制餐厅意图",
    "context_resolution": "追问上下文回填失败",
}


def _format_actual(actual: dict) -> str:
    parts = []
    if "error" in actual:
        return f"runner 异常: {actual['error']}"
    if actual.get("fast_route_miss"):
        parts.append("fast_route_miss=True (未命中快速路由，将走 LLM)")
    else:
        parts.append(f"路由路径={actual.get('route_path', 'N/A')}")
        parts.append(f"agents={actual.get('agents', [])}")
        if actual.get("intents"):
            parts.append(f"intents={actual['intents']}")
        if actual.get("fast_event"):
            parts.append(f"fast_event={actual['fast_event']}")
        else:
            parts.append("fast_event=空")
        if actual.get("needs_clarification") is not None:
            parts.append(f"needs_clarification={actual['needs_clarification']}")
        if actual.get("key_entities"):
            parts.append(f"key_entities={actual['key_entities']}")
    if "currency_extracted" in actual:
        parts.append(f"currency={actual['currency_extracted']}")
    if "place_type" in actual:
        parts.append(
            f"place: type={actual['place_type']} city='{actual['place_city']}' "
            f"keywords='{actual['place_keywords']}'"
        )
    return "\n    ".join(parts) or "(无)"


def _root_cause(case: dict, actual: dict) -> str:
    """根据类别+实际行为给出根因定位（基于代码阅读）。"""
    cat = case["category"]
    agents = actual.get("agents", [])
    if cat == "fast_route_hijack":
        if not agents:
            return (
                "`agents/intention_agent.py:267` `_fast_match` 未识别差旅信号"
                "（出差/天/开会/行程/安排），查询 fall through 到 LLM；"
                "但 fast route 顶部缺乏差旅信号短路逻辑，依赖 LLM 兜底，"
                "稳定性差。建议在 fast route 顶部主动检测差旅信号"
            )
        return (
            "`agents/intention_agent.py:267` `_fast_match` 命中单关键词（如'酒店'/'景点'）"
            "后直接返回，未检测差旅信号（出差/天/开会/行程/安排等），"
            "导致 LLM 路径的多意图识别与 fast_event 提取被绕过"
        )
    if cat == "city_extraction":
        return (
            "`agents/intention_agent.py:354-365` 等 各 *_PATTERNS 提取城市时只取首个"
            "匹配的城市关键词，无法区分'从A去B'的 origin/destination，"
            "多城市查询的出发地被丢失"
        )
    if cat == "keyword_too_broad":
        return (
            "`agents/intention_agent.py:67-135` 的关键词集含'住/玩/大餐/逛逛'等"
            "生活化用词，正则 `(.{2,8}?).*?(关键词)` 匹配过宽，"
            "在非查询场景（叙述/提议）下误命中"
        )
    if cat == "date_extraction_gap":
        return (
            "`agents/intention_agent.py:479` 日期正则仅覆盖"
            "(明天|后天|今天|\\d月\\d日|YYYY-MM-DD)，"
            "下周X/月底/节假日名（中秋、国庆、春节）/日期范围均无法解析"
        )
    if cat == "elliptical_limit":
        return (
            "`agents/intention_agent.py:226-230` `_resolve_elliptical` 仅在"
            "`_CITY_KEYWORDS`（直辖市/省会/计划单列市等）中查找，"
            "虹桥/大学城/香格里拉/浦东新区/嘉兴等不在列表导致追问无法消解"
        )
    if cat == "place_type_suppression":
        return (
            "`.claude/skills/place-search/script/agent.py:205-224, 349-364` "
            "`_is_restaurant_query` / `_is_scenic_query` 用 `_NON_*_KEYWORDS` "
            "前置排除，'酒店/民宿/住的地方'等词出现即返回 False，"
            "忽略'附近/周边/旁边/楼下/对面'等修饰词后的真实意图"
        )
    if cat == "event_extraction_loss":
        return (
            "`agents/intention_agent.py:577-581` fast route 命中后跳过 LLM，"
            "结构化字段 `fast_event`（origin/destination/start_date/trip_purpose）"
            "完全不生成；`orchestration_agent.py:476-507` 的 trip_history 保存逻辑"
            "依赖 fast_event，导致差旅信息无法写入长期记忆"
        )
    if cat == "currency_ambiguity":
        return (
            "`agents/intention_agent.py:159-183` `_extract_currency` 用"
            "`(\\d+)\\s*([^\\d\\s]+?)\\s*(多少|换|兑|...)` 匹配，"
            "金额+元+非货币动词的组合（如'打车花了100元'）可能被误判为汇率查询"
        )
    if cat == "memory_false_trigger":
        return (
            "`agents/intention_agent.py:201-207` `_MEMORY_PATTERNS` 含 `(我去过)` "
            "等宽匹配，'去年去过北京今年还想去'/'想去北京' 等查询会被误识别为历史查询"
        )
    if cat == "translation_lang_gap":
        return (
            "`agents/intention_agent.py:185-189` `_TRANSLATION_PATTERNS` 语言白名单"
            "仅含英/日/韩/法/德/中，俄语/阿拉伯语/西班牙语等常见语言无法快速路由，"
            "英文白名单缺 Russian/Spanish/Arabic"
        )
    if cat == "location_context_over_extract":
        return (
            "`.claude/skills/place-search/script/agent.py:481-526` "
            "`_extract_location_context` 用 `([一-龥]{2,6}(区|镇|...|大学|...))` "
            "提取地标，'上海大学'/'北京大学'被整体提取为 keywords 前缀；"
            "城市名若未在查询中显式出现（如'复旦大学邯郸校区附近酒店'），"
            "`_extract_city` 返回空"
        )
    if cat == "multi_intent_collapse":
        return (
            "`agents/intention_agent.py:317-348` 天气分支只附加 hotel_search，"
            "其他组合（天气+美食、景点+酒店、三意图）均不会生成多 agent_schedule；"
            "酒店/餐厅/景点单分支互斥，无法在 fast route 内组合"
        )
    if cat == "train_ticket_ambiguity":
        if "train_ticket" in agents:
            return (
                "`agents/intention_agent.py:191-199` `_TRAIN_PATTERNS` 含 "
                "`([一-龥]{2,4})\\s*[到至去往]\\s*([一-龥]{2,4})` ，"
                "'A去B玩/出差/旅游'等差旅场景被误判为火车票查询"
            )
        if "scenic_search" in agents:
            return (
                "`agents/intention_agent.py:113-136` `_SCENIC_KEYWORDS` 含'旅游/游玩'，"
                "'A到B旅游'中的'旅游'被当作景点搜索信号，"
                "差旅意图被误判为景点搜索"
            )
        if "hotel_search" in agents:
            return (
                "`agents/intention_agent.py:67-85` `_HOTEL_PATTERNS` 命中查询中的"
                "住宿相关词，差旅意图被误判为酒店搜索"
            )
        return (
            "`agents/intention_agent.py:191-199` `_TRAIN_PATTERNS` 含 "
            "`([一-龥]{2,4})\\s*[到至去往]\\s*([一-龥]{2,4})` ，"
            "'A去B玩/出差/旅游'等差旅场景可能被误判"
        )
    if cat == "weather_mixed_query":
        if "hotel_search" in agents and "information_query" in agents:
            return (
                "`agents/intention_agent.py:317-348` 天气分支提取单一 city，"
                "hotel_search 复用同一 city；'北京天气和上海酒店'的酒店城市被错配为北京"
            )
        if "information_query" in agents and len(agents) == 1:
            return (
                "`agents/intention_agent.py:317-348` 天气分支仅识别首城市，"
                "第二个城市（如'上海天气和北京天气'中的北京）被丢弃"
            )
        return (
            "`agents/intention_agent.py:317-348` 天气分支只附加 hotel_search，"
            "其他组合（天气+美食、景点+酒店、三意图）均不会生成多 agent_schedule"
        )
    if cat == "restaurant_in_lodging_context":
        return (
            "`.claude/skills/place-search/script/agent.py:205-224` "
            "`_is_restaurant_query` 中 `_NON_RESTAURANT_KEYWORDS` 前置排除，"
            "after_kw 检查只识别'附近/周边/旁边/楼下/对面'，"
            "'酒店里的餐厅'/'酒店早餐'等结构被压制为酒店搜索"
        )
    if cat == "context_resolution":
        if not actual.get("key_entities", {}).get("destination"):
            return (
                "`agents/intention_agent.py` fast route 命中 hotel/restaurant/scenic_search "
                "但 city 为空时未从对话历史回填，直接 return None 或返回空 destination；"
                "LLM prompt 的'关键信息缺失处理'未覆盖酒店/餐厅/景点搜索的历史回填规则"
            )
        return (
            "`agents/intention_agent.py` fast route 或 LLM 路径未正确从对话历史回填 destination"
        )
    return "（根因待人工补充）"


def _suggested_fix(cat: str) -> str:
    fixes = {
        "fast_route_hijack": "在 `_fast_match` 顶部增加差旅信号检测（出差/天/开会/行程/安排/\\d+天），命中即 `return None` 走 LLM",
        "city_extraction": "在 *_PATTERNS 中加入'从A[去/到/至/往]B'模式，分别捕获 origin 与 destination",
        "keyword_too_broad": "对 HOTEL/RESTAURANT/SCENIC 关键词集增加'搜索/查询/推荐/有哪些'等动词限定，避免单关键词命中",
        "date_extraction_gap": "扩展日期正则覆盖下周X/这周X/月底/月初/节假日名，并维护节假日→具体日期的映射表",
        "elliptical_limit": "`_resolve_elliptical` 的城市判定改为：先查 `_CITY_KEYWORDS`，未命中再尝试 `_COMMON_CITIES` 或地理名词库",
        "place_type_suppression": "`_is_restaurant_query`/`_is_scenic_query` 的 `_NON_*` 排除应改为：当 after_kw 含'附近/周边/旁边/楼下/对面'且其后有真实餐厅/景点词时返回 True",
        "event_extraction_loss": "在 fast route 各分支同步生成 `fast_event`（至少 destination/origin/start_date），或在差旅信号检测后强制走 LLM",
        "currency_ambiguity": "`_extract_currency` 在匹配后校验前后词是否为货币代码（USD/CNY/JPY 等），金额+元+非货币动词直接返回 None",
        "memory_false_trigger": "`_MEMORY_PATTERNS` 收紧'我去过'的匹配，要求同时含'查询/记录/历史/汇总'等查询动词",
        "translation_lang_gap": "扩展 `_TRANSLATION_PATTERNS` 语言白名单：俄语/西班牙语/阿拉伯语/葡萄牙语/意大利语/泰语/越南语等，英文版同步补充",
        "location_context_over_extract": "`_extract_location_context` 对'XX大学/XX学院'等地标分类单独标注，避免整体作为 keywords 前缀；或对未含城市名的查询直接返回城市提示",
        "multi_intent_collapse": "fast route 各分支识别到次要意图关键词时，主动附加对应 agent_schedule（如天气+美食附加 restaurant_search）",
        "train_ticket_ambiguity": "`_TRAIN_PATTERNS` 增加排除词（玩/出差/旅游/开会/行程/安排），命中后仍走 LLM 确认",
        "weather_mixed_query": "天气分支解析查询中的多城市，hotel_search 使用第二个城市而非复用天气城市",
        "restaurant_in_lodging_context": "`_is_restaurant_query` 的 after_kw 检查扩展到'里的/早餐/晚餐'等场景，识别真实餐厅意图",
        "context_resolution": "fast route 命中但 city 为空时从 dialogue_history 回填最近城市；LLM prompt 的缺失处理段扩展到酒店/餐厅/景点搜索",
    }
    return fixes.get(cat, "（待补充）")


def _build_report(results: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(results)
    bug_count = sum(1 for r in results if r["mismatches"])
    by_cat: dict[str, int] = {}
    for r in results:
        if r["mismatches"]:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1

    lines = []
    lines.append("# 逻辑审计 Bug 报告")
    lines.append("")
    lines.append(f"- 生成时间：{now}")
    lines.append(f"- 总用例：{total}")
    lines.append(f"- 发现 bug：{bug_count}")
    lines.append(f"- 审计范围：`agents/intention_agent.py` 的 `_fast_match` / "
                 "`_resolve_elliptical` / `_extract_currency`，"
                 "以及 `.claude/skills/place-search/script/agent.py` 的纯方法")
    lines.append(f"- 审计方式：仅静态分析，不调 LLM、不调外部 API")
    lines.append("")
    lines.append("## 按类别统计")
    lines.append("")
    lines.append("| 类别 | bug 数 |")
    lines.append("|------|--------|")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} ({_CATEGORY_LABEL.get(cat, '')}) | {n} |")
    lines.append("")

    lines.append("## Bug 列表")
    lines.append("")

    bug_idx = 0
    for r in results:
        if not r["mismatches"]:
            continue
        bug_idx += 1
        case = r["case"]
        actual = r["actual"]
        cat = case["category"]
        lines.append(f"### BUG-{bug_idx:03d} [{cat}] {case['query']}")
        lines.append("")
        lines.append(f"- **用例 ID**：{case['id']}")
        lines.append(f"- **类别**：{cat} ({_CATEGORY_LABEL.get(cat, '')})")
        if case.get("note"):
            lines.append(f"- **备注**：{case['note']}")
        lines.append(f"- **期望行为**：")
        lines.append("    ```")
        lines.append(json.dumps(case["expected"], ensure_ascii=False, indent=2))
        lines.append("    ```")
        lines.append(f"- **实际行为**：")
        lines.append("    ```")
        lines.append("    " + _format_actual(actual))
        lines.append("    ```")
        lines.append(f"- **不符项**：")
        for m in r["mismatches"]:
            lines.append(f"    - {m}")
        lines.append(f"- **根因定位**：{_root_cause(case, actual)}")
        lines.append(f"- **建议修复**：{_suggested_fix(cat)}")
        lines.append("")

    lines.append("## 附录：通过用例")
    lines.append("")
    passed = [r for r in results if not r["mismatches"]]
    if passed:
        lines.append("| ID | 类别 | 查询 |")
        lines.append("|----|------|------|")
        for r in passed:
            q = r["case"]["query"]
            if len(q) > 40:
                q = q[:40] + "..."
            lines.append(f"| {r['case']['id']} | {r['category']} | {q} |")
    else:
        lines.append("（无）")

    lines.append("")
    lines.append("---")
    lines.append("*本报告由 `tests/logic_audit/runner.py` 自动生成，"
                 "审计逻辑详见 `tests/logic_audit/README.md`*")
    return "\n".join(lines)


def main() -> int:
    case_files = sorted(CASES_DIR.glob("*.json"))
    if not case_files:
        print(f"[!] 未在 {CASES_DIR} 找到用例文件", file=sys.stderr)
        return 1

    results: list[dict] = []
    for cf in case_files:
        try:
            cases = json.loads(cf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[!] 解析 {cf.name} 失败: {e}", file=sys.stderr)
            return 1
        for case in cases:
            try:
                res = _check_case(case)
            except Exception as e:
                res = {
                    "actual": {"error": str(e)},
                    "mismatches": [f"runner 异常: {e}"],
                }
            results.append({
                "case": case,
                "category": case.get("category", "unknown"),
                "actual": res["actual"],
                "mismatches": res["mismatches"],
            })

    report = _build_report(results)
    REPORT_PATH.write_text(report, encoding="utf-8")

    total = len(results)
    bugs = sum(1 for r in results if r["mismatches"])
    print(f"[OK] 审计完成：{total} 用例，{bugs} bug")
    print(f"[OK] 报告已写入：{REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
