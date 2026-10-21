"""火车票日期解析回归测试（不联网）。

2026-10-21 22:41 用户问「看看明早从北京去上海的高铁票有哪些」，
系统查了 **当天** 并返回「暂无余票」：因为只认「明天/后天/今天」，
「明早」落到兜底逻辑取当天，而当天车次已经发完。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib.util

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "train_ticket_agent", _ROOT / ".claude" / "skills" / "train-ticket" / "script" / "agent.py"
)
agent_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent_mod)


def _expect(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


@pytest.mark.parametrize(
    "word,offset",
    [
        ("今早", 0), ("今晚", 0), ("明天", 1), ("明早", 1), ("明晚", 1),
        ("后天", 2), ("大后天", 3),
    ],
)
def test_day_word_to_date(word, offset):
    assert agent_mod._day_word_to_date(word) == _expect(offset)


def test_normalize_passthrough_and_chinese_date():
    assert agent_mod._normalize_date_str("2026-10-22") == "2026-10-22"
    assert agent_mod._normalize_date_str("明早") == _expect(1)
    assert agent_mod._normalize_date_str("") == ""


def test_extract_travel_params_resolves_morning_word():
    agent = agent_mod.TrainTicketAgent()
    from_city, to_city, date_str = agent._extract_travel_params("看看明早从北京去上海的高铁票有哪些")
    assert (from_city, to_city) == ("北京", "上海")
    assert date_str == _expect(1), "「明早」必须解析成明天，而不是今天"


def test_extract_travel_params_keeps_explicit_date():
    agent = agent_mod.TrainTicketAgent()
    _, _, date_str = agent._extract_travel_params("查一下2026-10-25 北京到上海的高铁")
    assert date_str == "2026-10-25"


@pytest.mark.parametrize(
    "text,period",
    [
        ("明早从北京去上海", "morning"),
        ("今晚去上海的高铁", "evening"),
        ("下午从北京去上海", "afternoon"),
        ("明天北京到上海", ""),
    ],
)
def test_detect_period(text, period):
    assert agent_mod._detect_period(text) == period
