"""决策层阈值表。

为什么单独一份：阈值是**数据和业务**，不是代码。改阈值不应触发"改引擎"的评审。
支持从 data/decision_thresholds.json 覆盖（热加载，按 mtime 缓存），
线上调参不用重启。

初值来源：docs/decision-layer-dev-plan.md 第 2 节的 19 条基准
（choice 84%、noul 68% → 所以 choice 阈值更高、noul 门控更保守）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

OVERRIDE_PATH = os.environ.get(
    "ALIGO_DECISION_THRESHOLDS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "decision_thresholds.json"),
)

DEFAULT_THRESHOLDS: Dict[str, Any] = {
    # 主意图置信度：≥0.90 才允许直通（实测 top-1 84%，留一档余量）
    "p_intent": 0.90,
    # 低于该值视为"模型也不确定"，直接交回 LLM
    "p_intent_floor": 0.55,
    # 前置门控：P(is_request) 低于此值 → 判定为闲聊/陈述
    "p_is_request": 0.40,
    # 能力门控默认阈值（各门控可用 per_gate 覆盖）
    "p_gate": 0.80,
    "per_gate": {
        "want_trip": 0.80,
        "want_hotel": 0.75,
        "want_restaurant": 0.75,
        "want_scenic": 0.80,
        "want_info": 0.80,
        "want_memory": 0.85,
    },
    # 反问：低于该值明确不需要反问；高于 reverse 才反问；(0.3,0.7) 交给 LLM
    "p_clarify": 0.75,
    # veto：正则命中但决策层强烈反对时，允许撤销 fast-route
    "veto": {
        "p_is_request_below": 0.35,   # 明显不是请求
        "p_chitchat_above": 0.60,     # 或明确是闲聊
        "min_confident_intent": 0.60, # 且主意图不够自信时才否决
        "min_agree_margin": 0.15,     # 且正则命中的意图概率低于 top1 一定幅度
    },
    # 超时与熔断
    "timeout_sec": 8.0,
    "circuit_failure_threshold": 5,
    "circuit_recovery_sec": 60.0,
}

_cache: Dict[str, Any] = {"mtime": None, "value": None, "loaded_at": 0.0}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_thresholds(path: str = None) -> Dict[str, Any]:
    """读阈值：默认值 ← 文件覆盖。文件坏了不影响主链路（记 warning 用默认值）。"""
    path = path or OVERRIDE_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return dict(DEFAULT_THRESHOLDS)

    if _cache["mtime"] == mtime and _cache["value"] is not None:
        return _cache["value"]

    try:
        with open(path, "r", encoding="utf-8") as fh:
            override = json.load(fh)
        if not isinstance(override, dict):
            raise ValueError("阈值文件必须是 JSON 对象")
        value = _deep_merge(DEFAULT_THRESHOLDS, override)
        _cache.update({"mtime": mtime, "value": value, "loaded_at": time.time()})
        logger.info("decision thresholds reloaded from %s", path)
        return value
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision thresholds load failed (%s): %s", path, exc)
        return dict(DEFAULT_THRESHOLDS)


def gate_threshold(name: str, th: Dict[str, Any] = None) -> float:
    th = th or load_thresholds()
    return float((th.get("per_gate") or {}).get(name, th.get("p_gate", 0.8)))
