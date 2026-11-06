"""决策层客户端：NeoHorse-Jev-4B（TokenRhythm /v1/decision）。

契约要点（实测 2026-11-06）：
    - 端点：POST {base}/decision，非 OpenAI 协议，**不能**走 /chat/completions；
    - 请求：{"model","state","questions"}，questions 1–16 题，题号自定义；
    - 响应：{"answers":{...},"input_tokens":N,"decision_seconds":s}；
    - 错误：401 key 无效 / 403 未获灰度 / 413 超限 / 422 参数 / 429 限流 / 5xx 上游。

设计约束（都是为了不拖垮主链路）：
    1. 任何失败都返回 None，绝不把异常抛给用户；上层降级到 LLM 或正则。
    2. 复用 utils/circuit_breaker.py：连续失败 5 次熔断 60 秒，半开自愈。
    3. 403 视为"永久没权限"，进程内打标记不再尝试，避免每条消息都白等 200ms。
    4. 不 import config.py（并行会话正在改它）；配置全部来自环境变量。

环境变量：
    NEOHOUSE_API_KEY / NEOHOUSE_BASE_URL / NEOHOUSE_MODEL
    ALIGO_DECISION_MODE=off|shadow|assist|primary
    ALIGO_DECISION_TIMEOUT=8
    ALIGO_DECISION_SHADOW_DIR=data/decision_shadow
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.circuit_breaker import CircuitBreaker
from utils.decision_schema import (
    GATE_TO_INTENT,
    build_questions,
    build_state,
)
from utils.decision_thresholds import gate_threshold, load_thresholds
from utils.decision_types import RouteDecision, ShadowRecord

logger = logging.getLogger(__name__)

MODES = ("off", "shadow", "assist", "primary")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DecisionUnavailable(Exception):
    """决策层不可用（配置缺失、熔断、网络、协议错误）。调用方应降级。"""


def _mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else "***"


class DecisionEngine:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://tokenrhythm.studio/v1",
        model: str = "NeoHorse-Jev-4B",
        mode: str = "shadow",
        timeout: float = 8.0,
        shadow_dir: str = "",
        circuit: Optional[CircuitBreaker] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.mode = mode if mode in MODES else "shadow"
        self.timeout = float(timeout)
        self.shadow_dir = shadow_dir or os.path.join(_PROJECT_ROOT, "data", "decision_shadow")
        self.circuit = circuit or CircuitBreaker(
            failure_threshold=int(load_thresholds().get("circuit_failure_threshold", 5)),
            recovery_timeout_sec=float(load_thresholds().get("circuit_recovery_sec", 60.0)),
        )
        self._forbidden = False            # 403 永久禁用
        self._log_lock = threading.Lock()
        self._last_error = ""
        # 同 query 短时重复调用走缓存（影子模式常见；也降低 429 概率）
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = float(os.environ.get("ALIGO_DECISION_CACHE_TTL", "300"))

    # ── 构造 ────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> Optional["DecisionEngine"]:
        """直接读环境变量（测试与脚本用）。没配 key 或 mode=off 时返回 None。"""
        return cls.from_config({
            "mode": os.environ.get("ALIGO_DECISION_MODE", "off"),
            "api_key": os.environ.get("NEOHOUSE_API_KEY", ""),
            "base_url": os.environ.get("NEOHOUSE_BASE_URL", "https://tokenrhythm.studio/v1"),
            "model": os.environ.get("NEOHOUSE_MODEL", "NeoHorse-Jev-4B"),
            "timeout": float(os.environ.get("ALIGO_DECISION_TIMEOUT", "8")),
            "shadow_dir": os.environ.get("ALIGO_DECISION_SHADOW_DIR", ""),
        })

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> Optional["DecisionEngine"]:
        """从 config.DECISION_CONFIG（或同形 dict）构造。"""
        mode = (cfg.get("mode") or "off").strip().lower()
        key = (cfg.get("api_key") or "").strip()
        if mode == "off" or not key:
            return None
        return cls(
            api_key=key,
            base_url=cfg.get("base_url") or "https://tokenrhythm.studio/v1",
            model=cfg.get("model") or "NeoHorse-Jev-4B",
            mode=mode,
            timeout=float(cfg.get("timeout") or 8.0),
            shadow_dir=cfg.get("shadow_dir") or os.path.join(_PROJECT_ROOT, "data", "decision_shadow"),
        )

    # ── 状态 ────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self.mode != "off" and bool(self.api_key) and not self._forbidden

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "model": self.model,
            "base_url": self.base_url,
            "enabled": self.enabled,
            "forbidden": self._forbidden,
            "circuit": self.circuit.get_status(),
            "last_error": self._last_error,
        }

    # ── HTTP ────────────────────────────────────────────────
    def _post_blocking(self, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/decision",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    @staticmethod
    def _classify(exc: BaseException) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            return {
                401: "auth", 403: "forbidden", 413: "too_large",
                422: "bad_request", 429: "rate_limit",
                500: "upstream", 502: "upstream", 503: "upstream", 504: "upstream",
            }.get(exc.code, f"http_{exc.code}")
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return "timeout"
        text = str(exc).lower()
        if "timed out" in text or "timeout" in text:
            return "timeout"
        return "network"

    async def decide(
        self,
        state: str,
        questions: Dict[str, dict],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发一次决策请求，返回原始 JSON。失败抛 DecisionUnavailable。"""
        if not self.enabled:
            raise DecisionUnavailable("决策层未启用")
        if not self.circuit.allow_call():
            raise DecisionUnavailable("决策层熔断中")

        timeout = float(timeout or self.timeout)
        payload = {"model": self.model, "state": state, "questions": questions}

        try:
            data = await asyncio.to_thread(self._post_blocking, payload, timeout)
        except BaseException as exc:  # noqa: BLE001
            kind = self._classify(exc)
            self.circuit.record_failure()
            self._last_error = f"{kind}: {str(exc)[:160]}"
            if kind == "forbidden":
                self._forbidden = True
                logger.error("decision layer disabled (403 not in gray list); fallback permanently. %s",
                             self._last_error)
            else:
                logger.warning("decision call failed (%s): %s", kind, self._last_error)
            raise DecisionUnavailable(self._last_error) from exc

        self.circuit.record_success()
        return data

    # ── 项目封装 ────────────────────────────────────────────
    async def route(
        self,
        query: str,
        history: Optional[List[str]] = None,
        entities: Optional[Dict[str, str]] = None,
    ) -> Optional[RouteDecision]:
        """拼题面 → 发请求 → 套阈值 → 归一化。任何异常返回 None。"""
        if not self.enabled or not (query or "").strip():
            return None

        key = self._cache_key(query, history, entities)
        cached = self._cache_get(key)
        if cached is not None:
            return dataclasses.replace(cached, trace_id=uuid.uuid4().hex[:12], latency_ms=0.0)

        state = build_state(query, history, entities)
        t0 = time.monotonic()
        try:
            data = await self.decide(state, build_questions())
        except DecisionUnavailable:
            return None

        latency_ms = (time.monotonic() - t0) * 1000
        try:
            decision = self._parse(data, latency_ms)
            self._cache_put(key, decision)
            return decision
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"parse: {exc}"
            logger.warning("decision response parse failed: %s", exc)
            return None

    # ── 决策缓存 ────────────────────────────────────────────
    @staticmethod
    def _cache_key(query: str, history: Optional[List[str]], entities: Optional[Dict[str, str]]) -> str:
        raw = "|".join([query.strip(), " / ".join((history or [])[-2:]), json.dumps(entities or {}, ensure_ascii=False, sort_keys=True)])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str):
        if self._cache_ttl <= 0:
            return None
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, decision = hit
        if time.time() - ts > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return decision

    def _cache_put(self, key: str, decision) -> None:
        if self._cache_ttl <= 0:
            return
        if len(self._cache) > 512:
            self._cache.clear()
        self._cache[key] = (time.time(), decision)

    def route_sync(self, query: str, history: Optional[List[str]] = None,
                   entities: Optional[Dict[str, str]] = None) -> Optional[RouteDecision]:
        """同步入口（脚本 / 同步函数里用）。不要在事件循环里调用。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.route(query, history, entities))
        raise RuntimeError("route_sync 不能在事件循环内调用，请改用 await route()")

    def _parse(self, data: Dict[str, Any], latency_ms: float) -> RouteDecision:
        th = load_thresholds()
        answers = data.get("answers") or {}

        intent_ans = answers.get("intent") or {}
        intent = intent_ans.get("choice") or "chitchat"
        probs = {k: float(v) for k, v in (intent_ans.get("probabilities") or {}).items()}
        p_intent = float(probs.get(intent, 0.0))

        request_ans = answers.get("is_request") or {}
        p_request = float(request_ans.get("noul", 0.5))

        clarify_ans = answers.get("need_clarify") or {}
        p_clarify = float(clarify_ans.get("noul", 0.0))

        gates: Dict[str, float] = {}
        flags: Dict[str, bool] = {}
        for gate in GATE_TO_INTENT:
            ans = answers.get(gate) or {}
            p = float(ans.get("noul", 0.0))
            gates[gate] = round(p, 4)
            flags[gate] = p >= gate_threshold(gate, th)

        decision = RouteDecision(
            intent=intent,
            p_intent=round(p_intent, 4),
            intent_probs={k: round(v, 4) for k, v in probs.items()},
            is_request=p_request >= float(th.get("p_is_request", 0.4)),
            p_is_request=round(p_request, 4),
            need_clarify=round(p_clarify, 4),
            gates=gates,
            gate_flags=flags,
            latency_ms=round(latency_ms, 1),
            input_tokens=int(data.get("input_tokens") or 0),
            decision_seconds=float(data.get("decision_seconds") or 0.0),
        )
        # 冲突用"原始门控"判定（回填前的事实）
        decision.conflicts = self._conflicts(decision)

        # choice 头比独立 noul 头准（84% vs 68%，见计划第 2 节）：
        # 主意图够自信时，把它对应的门控回填为真，避免"意图对了、门控漏了"。
        # 只影响 downstream 调度与统计，不影响上面的冲突留痕。
        reverse = {v: k for k, v in GATE_TO_INTENT.items()}
        primary_gate = reverse.get(intent)
        floor = float(th.get("p_intent_floor", 0.55))
        if primary_gate and p_intent >= floor:
            decision.gate_flags[primary_gate] = True
        return decision

    @staticmethod
    def _conflicts(d: RouteDecision) -> List[str]:
        """choice 与 noul 打架时留痕（实测两者独立计算，会互相矛盾）。"""
        issues: List[str] = []
        # 主意图是某搜索类，但对应门控没开
        reverse = {v: k for k, v in GATE_TO_INTENT.items()}
        gate_name = reverse.get(d.intent)
        if gate_name and not d.gate_flags.get(gate_name, False):
            issues.append(f"intent={d.intent} 但 {gate_name}={d.gates.get(gate_name, 0):.2f} 未过阈值")
        # 主意图是 chitchat，但某个门控很硬
        if d.intent == "chitchat":
            hot = [g for g, on in d.gate_flags.items() if on]
            if hot:
                issues.append(f"intent=chitchat 但门控 {hot} 为真")
        # 非请求却给出具体技能意图
        if not d.is_request and d.intent not in ("chitchat",):
            issues.append(f"is_request=false 但 intent={d.intent}")
        return issues

    # ── 影子日志 ────────────────────────────────────────────
    def log(self, record: ShadowRecord) -> None:
        """JSONL 落盘。失败静默（日志不是主链路）。"""
        if self.mode == "off":
            return
        try:
            os.makedirs(self.shadow_dir, exist_ok=True)
            path = os.path.join(self.shadow_dir, datetime.now().strftime("%Y%m%d") + ".jsonl")
            line = record.to_json()
            with self._log_lock:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug("shadow log failed: %s", exc)


# ── 模块级单例（进程内复用连接语义与熔断状态）──────────────
_engine: Optional[DecisionEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> Optional[DecisionEngine]:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                engine = DecisionEngine.from_env()
                if engine is not None:
                    logger.info("decision layer enabled: mode=%s model=%s key=%s",
                                engine.mode, engine.model, _mask(engine.api_key))
                _engine = engine
    return _engine


def reset_engine(engine: Optional[DecisionEngine] = None) -> None:
    """测试用：替换/清空单例。"""
    global _engine
    _engine = engine
