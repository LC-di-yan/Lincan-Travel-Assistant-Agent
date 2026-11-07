# -*- coding: utf-8 -*-
"""天气快路由：评价/感叹句不得当成查询（影子回放暴露的真实缺陷）。

由来：2026-11-07 采集 24 条真实样本做影子回放，一致率 87.5%，
唯一「决策层比正则更准」的案例是「今天天气真不错啊」——
正则误判 information_query 去查天气，决策层判 chitchat(0.95)。
本测试锁定修复：评价句交给 LLM，正常天气查询仍走快路由。
"""
from __future__ import annotations

import sys
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.intention_agent import (  # noqa: E402
    _WEATHER_COMMENT_RE,
    _WEATHER_PATTERNS,
    _WEATHER_QUERY_SIGNAL_RE,
)


def _would_skip_fast(q: str) -> bool:
    """复现快路由里的守卫判定：命中天气模式 + 是评价句 + 无查询信号 → 放弃快路由。"""
    if not any(p.search(q) for p in _WEATHER_PATTERNS):
        return False
    return bool(_WEATHER_COMMENT_RE.search(q)) and not bool(_WEATHER_QUERY_SIGNAL_RE.search(q))


def test_weather_comment_is_not_treated_as_query():
    assert _would_skip_fast("今天天气真不错啊") is True


def test_comment_detector_covers_evaluation_wording():
    """守卫本身要能识别各种评价措辞（与是否命中天气模式无关）。"""
    for q in ["今天天气真好", "天气太热了", "这天气挺舒服", "明天天气很差"]:
        assert _WEATHER_COMMENT_RE.search(q), q
        assert not _WEATHER_QUERY_SIGNAL_RE.search(q), q


def test_comments_matching_weather_pattern_skip_fast_route():
    """既命中天气模式、又是评价句的，必须放弃快路由。"""
    for q in ["今天天气真好", "明天天气很差", "今天天气真不错啊"]:
        assert any(p.search(q) for p in _WEATHER_PATTERNS), q
        assert _would_skip_fast(q) is True, q


def test_real_weather_queries_still_use_fast_route():
    for q in ["杭州下周天气怎么样", "北京天气如何", "上海天气", "查一下广州天气",
              "深圳明天多少度", "成都天气会不会下雨"]:
        assert _would_skip_fast(q) is False, q


def test_comment_with_query_signal_still_uses_fast_route():
    """既有评价又明确提问 → 仍是查询，不能误杀。"""
    for q in ["天气真热啊，明天要不要下雨", "天气不错，杭州下周天气怎么样"]:
        assert _would_skip_fast(q) is False, q


def test_non_weather_queries_unaffected():
    for q in ["帮我找杭州的酒店", "出差住宿标准是多少", "嗯嗯我知道了"]:
        assert _would_skip_fast(q) is False, q
