# -*- coding: utf-8 -*-
"""决策层 TypeSafe/Jev 后端（升级计划 P7 决策项，协议实测兼容）。

背景（2026-11-06 实测）：
- NeoHorse 端点（tokenrhythm.studio）同时提供 /v1/decision（自研客户端路径）与
  /v1/systemone（TypeSafe SDK 标准路径），二者无鉴权时均返回 401（路径存在）；
- TypeSafe systemone 载荷 {state, model, questions} 与自研决策层逐字段同源，
  题面原语 noul/choice/score 同名；
- agentscope 的 `JevClassifierModel` 题面判别字面量是 binary/choice/score
  （SDK 层才叫 Noul/Choice/Score），因此要做一层类型翻译。

本模块把 agentscope 的 JevClassifierModel 适配成与 DecisionEngine.decide() 同接口，
输出自研 `_parse()` 期望的线格式 {"answers": {...}, "input_tokens": N, ...}。
RefusalAnswer 视为该次调用不可用（抛 ValueError → 上层 DecisionUnavailable → 回退 LLM）。

用法：`DecisionEngine(..., backend="jev")` 或环境变量 `ALIGO_DECISION_BACKEND=jev`。
默认 "custom"（原 /v1/decision urllib 客户端），零行为变化。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

__all__ = ["JevDecisionBackend", "translate_questions", "to_wire"]


def translate_questions(questions: Mapping[str, dict]) -> Dict[str, Any]:
    """自研题面（type=noul/choice/score 裸 dict）→ agentscope 分类器题面对象。

    - noul  → BinaryQuestion（criteria 为 BinaryCriteria(true/false)，自研题面没有则不传）
    - choice → ChoiceQuestion（criteria: dict[str, str]，与自研 INTENT_CRITERIA 同形）
    - score → ScoreQuestion
    """
    from agentscope.classifier import ChoiceQuestion, ScoreQuestion
    from agentscope.classifier._question import BinaryQuestion

    out: Dict[str, Any] = {}
    for name, q in questions.items():
        qtype = q.get("type")
        instructions = q.get("instructions") or ""
        if qtype == "noul":
            out[name] = BinaryQuestion(instructions=instructions)
        elif qtype == "choice":
            out[name] = ChoiceQuestion(instructions=instructions, criteria=dict(q.get("criteria") or {}))
        elif qtype == "score":
            out[name] = ScoreQuestion(instructions=instructions)
        else:
            raise ValueError(f"未知题面类型 {qtype!r}（question={name}）")
    return out


def to_wire(resp: Any, decision_seconds: float = 0.0) -> Dict[str, Any]:
    """ClassifierResponse → 自研 _parse() 期望的线格式。

    - BinaryAnswer(probability)  → {"noul": probability}
    - ChoiceAnswer(choice, probabilities) → {"choice": ..., "probabilities": ...}
    - ScoreAnswer(score) → {"score": score}
    - RefusalAnswer → ValueError（上层回退 LLM，比静默默认值安全）
    """
    answers: Dict[str, Dict[str, Any]] = {}
    for name, ans in (resp.content or {}).items():
        atype = getattr(ans, "type", None)
        if atype == "binary_answer":
            answers[name] = {"noul": float(getattr(ans, "probability", 0.0))}
        elif atype == "choice_answer":
            answers[name] = {
                "choice": getattr(ans, "choice", None) or "chitchat",
                "confidence": float(getattr(ans, "confidence", 0.0)),
                "probabilities": {k: float(v) for k, v in (getattr(ans, "probabilities", None) or {}).items()},
            }
        elif atype == "score_answer":
            answers[name] = {"score": float(getattr(ans, "score", 0.0))}
        elif atype == "refusal_answer":
            raise ValueError(f"模型拒答题面 {name!r}（refusal）")
        else:
            raise ValueError(f"未知答案类型 {atype!r}（question={name}）")

    usage = getattr(resp, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
    return {
        "model": getattr(resp, "model", None),
        "answers": answers,
        "input_tokens": int(input_tokens) if input_tokens is not None else 0,
        "decision_seconds": round(decision_seconds, 3),
    }


class JevDecisionBackend:
    """与 DecisionEngine.decide() 同接口的 TypeSafe/Jev 后端。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 8.0):
        from agentscope.classifier import JevClassifierModel
        from agentscope.credential import TypeSafeCredential

        # TypeSafe SDK 会自己在 base_url 后拼 /v1/systemone；
        # 项目配置的 base_url 惯例带 /v1（https://tokenrhythm.studio/v1），必须剥掉，
        # 否则变成 /v1/v1/systemone（实测 404/400）。
        clean = base_url.rstrip("/")
        if clean.endswith("/v1"):
            clean = clean[: -len("/v1")]
        self._model = JevClassifierModel(
            credential=TypeSafeCredential(api_key=api_key, base_url=clean),
            model=model,
            timeout=float(timeout),
            max_retries=1,
            retry_delay=0.5,
        )
        # 网关兼容性 workaround（2026-11-06 实测）：typesafe-sdk 的 Config 默认 compression="zstd"，
        # body ≥1024B 会压缩传输，而 tokenrhythm 的 nginx 对压缩请求体报
        # 400 "Request body size did not match Content-Length"（小 body 不触发，故单发探针不炸）。
        # SDK 未暴露开关，只能改 _config；仅影响本模型实例。
        try:
            # 注意：必须用 None 而不是 False —— SDK 的判断是 `compression is not None`，
            # 传 False 会被当成编码器名（报 'bool' object has no attribute 'encode'）。
            self._model.client._config.compression = None
        except AttributeError:
            logger.warning("typesafe-sdk 结构变化：未能关闭 zstd 压缩，大题面可能 400")

    async def decide(self, state: str, questions: Mapping[str, dict], timeout: Optional[float] = None) -> Dict[str, Any]:
        import time

        t0 = time.monotonic()
        translated = translate_questions(questions)
        resp = await self._model(state, translated)
        seconds = time.monotonic() - t0
        return to_wire(resp, decision_seconds=seconds)
