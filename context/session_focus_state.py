"""
会话焦点状态
用于维护当前会话中的短期上下文，如焦点城市、当前行程目的地等。
该状态不持久化，仅用于提升多轮对话中的上下文消解能力。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SessionFocusState:
    """会话焦点状态"""

    focus_city: Optional[str] = None
    current_trip_destination: Optional[str] = None
    last_search_city: Optional[str] = None
    # 最近一次「列表型」结果（车票/酒店/餐厅/景点），供「列出来 / 全部」这类追问展开
    # 结构：{"agent": "train_ticket", "data": {...}, "ts": 1700000000.0}
    last_list_result: Optional[Dict[str, Any]] = field(default=None)

    def update_from_intention(self, intention_data: dict) -> None:
        """根据意图识别结果更新焦点城市。"""
        if not isinstance(intention_data, dict):
            return

        key_entities = intention_data.get("key_entities") or {}
        fast_event = intention_data.get("fast_event") or {}

        destination = (
            key_entities.get("destination")
            or fast_event.get("destination")
        )
        if destination:
            self.focus_city = destination
            self.current_trip_destination = destination

        origin = fast_event.get("origin")
        if origin and not destination:
            self.focus_city = origin

    def update_from_search_result(self, city: str) -> None:
        """根据搜索结果更新最后搜索城市。"""
        if city:
            self.focus_city = city
            self.last_search_city = city

    def build_focus_hint(self) -> str:
        """构建给 IntentionAgent 的焦点提示。"""
        if not self.focus_city:
            return ""
        parts = [f"当前会话焦点城市：{self.focus_city}"]
        if self.current_trip_destination:
            parts.append(f"用户近期行程目的地：{self.current_trip_destination}")
        return "; ".join(parts)
