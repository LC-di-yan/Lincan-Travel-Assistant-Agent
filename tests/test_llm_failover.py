"""通道故障转移与错误分类的离线单测（不访问网络）。

对应 2026-10-20 事故：主通道 403 AccessDenied.Unpurchased 后，
所有智能体同时失效，且上游错误原文被写进记忆/前端。
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.llm_errors import classify, friendly, status_code  # noqa: E402
from utils.llm_failover import FailoverChatModel, should_failover  # noqa: E402


class _FakeHTTPError(Exception):
    """模拟 openai.APIStatusError：错误文本里带状态码和 JSON 体。"""

    def __init__(self, status_code, body="", type_=""):
        self.status_code = status_code
        super().__init__(f"Error code: {status_code} - {body or type_}")


def _channels(n=2):
    return [
        {"name": f"ch{i}", "base_url": f"https://ch{i}.test/v1",
         "api_key": "sk-test", "model_name": f"model-{i}"}
        for i in range(n)
    ]


def test_status_code_from_openai_style_message():
    exc = Exception("Error code: 403 - {'error': {'message': 'Access to model denied.'}}")
    assert status_code(exc) == 403
    assert classify(exc) == "entitlement"


def test_classify_main_cases():
    assert classify(_FakeHTTPError(401)) == "auth"
    assert classify(_FakeHTTPError(403, type_="AccessDenied.Unpurchased")) == "entitlement"
    assert classify(_FakeHTTPError(429)) == "rate_limit"
    assert classify(_FakeHTTPError(503)) == "upstream"
    assert classify(_FakeHTTPError(400)) == "bad_request"
    assert classify(Exception("Connection timed out")) == "timeout"
    assert classify(ValueError("no json"), stage="parse") == "parse"


def test_friendly_never_leaks_upstream_detail():
    exc = _FakeHTTPError(403, body="{'error': {'code': 'AccessDenied.Unpurchased'}}")
    msg = friendly(exc)
    assert "AccessDenied" not in msg and "403" not in msg
    assert "未授权" in msg or "额度" in msg


def test_arrears_is_distinguished_from_unpurchased():
    """阿里云百炼欠费返回 400 Arrearage；中转站只透 403，文案要能分开。"""
    arrears = _FakeHTTPError(
        400,
        body="{'error': {'message': 'Access denied, please make sure your account is in "
             "good standing.', 'type': 'Arrearage', 'code': 'Arrearage'}}",
    )
    assert classify(arrears) == "arrears"
    assert "欠费" in friendly(arrears)
    assert should_failover(arrears) is True

    unpurchased = _FakeHTTPError(403, type_="AccessDenied.Unpurchased")
    assert classify(unpurchased) == "entitlement"
    assert "欠费" not in friendly(unpurchased)


def test_should_failover_skips_client_errors():
    assert should_failover(_FakeHTTPError(403)) is True
    assert should_failover(_FakeHTTPError(500)) is True
    assert should_failover(TimeoutError("read timeout")) is True
    assert should_failover(_FakeHTTPError(400)) is False


def _model_with_fakes(fakes):
    m = FailoverChatModel(_channels(len(fakes)))
    m._models = {i: f for i, f in enumerate(fakes)}
    return m


def test_failover_moves_to_next_channel():
    calls = []

    async def bad(*a, **k):
        calls.append("bad")
        raise _FakeHTTPError(403, type_="AccessDenied.Unpurchased")

    async def good(*a, **k):
        calls.append("good")
        return {"text": "ok"}

    m = _model_with_fakes([bad, good])
    assert asyncio.run(m([{"role": "user", "content": "ping"}])) == {"text": "ok"}
    assert calls == ["bad", "good"]
    assert m.active_index == 1          # 记住可用通道
    assert m.active_name == "ch1 [model-1]"

    # sticky：下一次直接从可用通道开始，不再打挂掉的通道
    calls.clear()
    asyncio.run(m([]))
    assert calls == ["good"]


def test_all_channels_down_raises_last_error():
    async def bad(*a, **k):
        raise _FakeHTTPError(403)

    m = _model_with_fakes([bad, bad])
    with pytest.raises(_FakeHTTPError):
        asyncio.run(m([]))


def test_bad_request_does_not_failover():
    """400 参数问题换通道没用，应由调用方（plan-trip）去掉参数重试。"""
    calls = []

    async def bad(*a, **k):
        calls.append("bad")
        raise _FakeHTTPError(400)

    async def good(*a, **k):
        calls.append("good")
        return {"text": "ok"}

    m = _model_with_fakes([bad, good])
    with pytest.raises(_FakeHTTPError):
        asyncio.run(m([]))
    assert calls == ["bad"]


def test_probe_picks_first_working_channel():
    async def bad(*a, **k):
        raise _FakeHTTPError(403)

    async def good(*a, **k):
        return {"text": "pong"}

    m = _model_with_fakes([bad, good])
    report = asyncio.run(m.probe())
    assert report["active"] == "ch1"
    assert [c["ok"] for c in report["channels"]] == [False, True]


def test_total_budget_stops_endless_waiting():
    """两个通道都卡住时，整链不能被拖到 3 分钟（线上出现过 183s 无响应）。"""

    async def stuck(*a, **k):
        await asyncio.sleep(10)
        return {"text": "too late"}

    m = FailoverChatModel(_channels(2), total_timeout=0.5)
    m._models = {0: stuck, 1: stuck}

    t0 = time.monotonic()
    with pytest.raises(TimeoutError) as err:
        asyncio.run(m([]))
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"总预算没生效，实际耗时 {elapsed:.1f}s"
    assert "超时" in str(err.value) or "未返回" in str(err.value)
