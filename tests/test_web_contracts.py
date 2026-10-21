"""Web API contract tests for the React frontend.

These are integration tests: they expect a running Aligo server.

    python -m pytest tests/test_web_contracts.py -q
    ALIGO_TEST_BASE_URL=http://127.0.0.1:3003 ...

TTS/narration tests are opt-in and expect a server started with a mock
upstream (see tests/mock_audio_provider.py):

    ALIGO_AUDIO_BASE_URL=http://127.0.0.1:3014 python -m pytest ...
"""
import json
import os
import uuid
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("ALIGO_TEST_BASE_URL", "http://127.0.0.1:3003").rstrip("/")
AUDIO_URL = os.environ.get("ALIGO_AUDIO_BASE_URL", "").rstrip("/")
MEMORY_DIR = Path(__file__).resolve().parent.parent / "data" / "memory"


def _client(base: str = BASE_URL, timeout: float = 30) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=timeout)


def _skip_if_down(base: str):
    try:
        r = httpx.get(base + "/api/health", timeout=3)
        if r.status_code != 200:
            pytest.skip(f"server {base} unhealthy: HTTP {r.status_code}")
    except Exception as exc:
        pytest.skip(f"server {base} not running: {exc}")


@pytest.fixture()
def test_user():
    user = "pytest_web_" + uuid.uuid4().hex[:10]
    yield user
    try:
        (MEMORY_DIR / f"{user}.json").unlink(missing_ok=True)
    except OSError:
        pass


def _sse_events(resp):
    event = ""
    for line in resp.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            raw = line[5:].strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield event, payload
            event = ""


def test_health_and_static_index():
    _skip_if_down(BASE_URL)
    with _client() as c:
        assert c.get("/api/health").status_code == 200
        index = c.get("/")
        assert index.status_code == 200
        assert "text/html" in index.headers.get("content-type", "")
        assert "no-store" in index.headers.get("cache-control", "")


def test_session_and_read_endpoints(test_user):
    _skip_if_down(BASE_URL)
    with _client() as c:
        session = c.post("/api/session/new", json={"user_id": test_user})
        assert session.status_code == 200
        sid = session.json()["session_id"]
        assert sid

        history = c.get("/api/history", params={"user_id": test_user, "session_id": sid})
        assert history.status_code == 200
        body = history.json()
        assert body["trips"] == []
        assert body["statistics"]["total_trips"] == 0

        prefs = c.get("/api/preferences", params={"user_id": test_user, "session_id": sid})
        assert prefs.status_code == 200
        assert prefs.json()["preferences"] == {}

        expenses = c.get("/api/expenses", params={"user_id": test_user, "session_id": sid})
        assert expenses.status_code == 200
        assert expenses.json()["expenses"] == []
        assert expenses.json()["total"] == 0


def test_plugin_and_persona_contracts():
    _skip_if_down(BASE_URL)
    with _client() as c:
        plugins = c.get("/api/plugins")
        assert plugins.status_code == 200
        names = {p["name"] for p in plugins.json()["plugins"]}
        assert {"hotel-search", "place-search", "translation", "visa-info"} <= names
        assert all({"name", "enabled", "loaded"} <= set(p) for p in plugins.json()["plugins"])

        personas = c.get("/api/tts/personas")
        assert personas.status_code == 200
        ps = personas.json()["personas"]
        assert ps and all({"id", "label", "voice", "lang", "sample_text"} <= set(p) for p in ps)


def test_history_newest_first_contract():
    """The API promises newest-first ordering for both JSON and PG stores."""
    _skip_if_down(BASE_URL)
    with _client() as c:
        r = c.get("/api/history", params={"user_id": "default_user"})
        assert r.status_code == 200
        dates = [t.get("start_date") or t.get("timestamp") or "" for t in r.json()["trips"]]
        assert dates == sorted(dates, reverse=True)


@pytest.mark.skipif(not AUDIO_URL, reason="ALIGO_AUDIO_BASE_URL not set")
def test_tts_stream_contract():
    _skip_if_down(AUDIO_URL)
    chunks = 0
    with _client(AUDIO_URL, timeout=60) as c:
        with c.stream("POST", "/api/tts", json={"text": "音频测试", "persona_id": "loli_guide"}) as r:
            assert r.status_code == 200
            for event, payload in _sse_events(r):
                if event == "audio":
                    chunks += 1
                    assert payload.get("chunk")
    assert chunks >= 2


@pytest.mark.skipif(not AUDIO_URL, reason="ALIGO_AUDIO_BASE_URL not set")
def test_narrate_stream_contract():
    _skip_if_down(AUDIO_URL)
    text = ""
    with _client(AUDIO_URL, timeout=60) as c:
        with c.stream(
            "POST",
            "/api/narrate",
            json={"intention": "memory_query", "result_data": {"answer": "测试"}, "persona_id": "loli_guide"},
        ) as r:
            assert r.status_code == 200
            for event, payload in _sse_events(r):
                if event == "delta":
                    text += payload.get("text", "")
    assert text
