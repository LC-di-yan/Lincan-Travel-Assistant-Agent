"""
会话焦点状态与位置指代消解测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context.session_focus_state import SessionFocusState
from agents.intention_agent import _resolve_deixis


def test_resolve_deixis_with_history():
    dialogue = [
        "用户: 明天从北京去上海出差3天",
        "助手: 已规划3天行程：上海出差3日行程，目的地：上海。",
    ]
    resolved, city = _resolve_deixis("附近有哪些酒店和餐厅", dialogue)
    assert city == "上海"
    assert "上海" in resolved
    assert "附近" not in resolved


def test_resolve_deixis_no_history():
    resolved, city = _resolve_deixis("附近有哪些酒店", [])
    assert city is None
    assert resolved == "附近有哪些酒店"


def test_resolve_deixis_respects_explicit_city():
    dialogue = [
        "用户: 明天从北京去上海出差3天",
        "助手: 已规划3天行程：上海出差3日行程，目的地：上海。",
    ]
    resolved, city = _resolve_deixis("北京有哪些酒店", dialogue)
    assert city is None  # 不应替换，因为用户已明确指定城市
    assert resolved == "北京有哪些酒店"


def test_resolve_deixis_various_terms():
    dialogue = [
        "用户: 下周去成都旅游",
        "助手: 成都5日行程，目的地：成都。",
    ]
    for term in ["附近", "周边", "那边", "当地"]:
        resolved, city = _resolve_deixis(f"{term}有什么好吃的", dialogue)
        assert city == "成都", term
        assert "成都" in resolved, term


def test_session_focus_state_update_from_intention():
    fs = SessionFocusState()
    fs.update_from_intention({
        "key_entities": {"destination": "上海"},
        "fast_event": {"origin": "北京", "destination": "上海"},
    })
    assert fs.focus_city == "上海"
    assert fs.current_trip_destination == "上海"


def test_session_focus_state_build_hint():
    fs = SessionFocusState()
    assert fs.build_focus_hint() == ""

    fs.focus_city = "上海"
    fs.current_trip_destination = "上海"
    hint = fs.build_focus_hint()
    assert "上海" in hint
    assert "焦点城市" in hint
