"""决策层的数据结构。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RouteDecision:
    """一次决策的归一化结果。"""

    intent: str
    p_intent: float
    intent_probs: Dict[str, float] = field(default_factory=dict)
    is_request: bool = True
    p_is_request: float = 0.0
    need_clarify: float = 0.0
    gates: Dict[str, float] = field(default_factory=dict)
    gate_flags: Dict[str, bool] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    input_tokens: int = 0
    decision_seconds: float = 0.0
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # ── 便捷属性 ─────────────────────────────────────────
    @property
    def is_chitchat(self) -> bool:
        return self.intent == "chitchat" or not self.is_request

    @property
    def second_intent(self) -> tuple[str, float]:
        """非 top1 的最高分（用于判断 margin）。"""
        rest = {k: v for k, v in self.intent_probs.items() if k != self.intent}
        if not rest:
            return "", 0.0
        name = max(rest, key=rest.get)
        return name, float(rest[name])

    @property
    def margin(self) -> float:
        return float(self.p_intent - self.second_intent[1])

    @property
    def active_gates(self) -> List[str]:
        return [g for g, on in self.gate_flags.items() if on]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["margin"] = round(self.margin, 4)
        d["active_gates"] = self.active_gates
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ShadowRecord:
    """影子日志一条。JSONL 落地，供 tools/replay_shadow.py 回放。"""

    kind: str                 # "decision" | "outcome"
    query: str
    trace_id: str
    mode: str
    ts: float = field(default_factory=time.time)
    decision: Optional[Dict[str, Any]] = None
    regex_agents: List[str] = field(default_factory=list)
    regex_intents: List[str] = field(default_factory=list)
    final_path: str = ""      # "fast" | "decision" | "llm" | "elliptical" | "error"
    final_agents: List[str] = field(default_factory=list)
    final_intents: List[str] = field(default_factory=list)
    error: str = ""
    latency_ms: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)
