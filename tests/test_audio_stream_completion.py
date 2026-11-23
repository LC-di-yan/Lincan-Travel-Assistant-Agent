import json
from unittest.mock import Mock

import httpx
import pytest

from server.routes import narrate, tts


@pytest.mark.parametrize("service", ["tts", "narrate"])
@pytest.mark.parametrize(("ending", "has_data", "ok"), [
    ("[DONE]", True, True), ("stop", True, True), ("", True, False),
    ("length", True, False), ("[DONE]", False, False), ("error", True, False),
])
async def test_audio_completion_and_circuit_use_actual_upstream_outcome(monkeypatch, service, ending, has_data, ok):
    delta = {"audio": {"data": "AAAA"}} if service == "tts" else {"content": "测试"}
    payload = [json.dumps({"choices": [{"delta": delta}]})] if has_data else []
    if ending in ("length", "stop"):
        payload.append(json.dumps({"choices": [{"delta": {}, "finish_reason": ending}]}))
    if ending == "error":
        payload.append(json.dumps({"error": {"message": "测试错误"}}))
    if ending in ("[DONE]", "length", "error"):
        payload.append("[DONE]")
    body = "".join(f"data: {line}\n\n" for line in payload)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    circuit = Mock()
    if service == "tts":
        monkeypatch.setitem(tts.TTS_CONFIG, "api_key", "offline")
        monkeypatch.setattr(tts, "_tts_circuit", circuit)
        response = await tts.tts(tts.TTSRequest(text="测试"))
    else:
        monkeypatch.setitem(narrate.NARRATION_CONFIG, "api_key", "offline")
        monkeypatch.setattr(narrate, "_narration_circuit", circuit)
        response = await narrate.narrate(narrate.NarrateRequest(result_data={"answer": "测试"}))
    events = [evt["event"] async for evt in response.body_iterator]
    assert events[-1] == ("done" if ok else "error")
    assert circuit.record_success.call_count == int(ok)
    assert circuit.record_failure.call_count == int(not ok)
