from types import SimpleNamespace

import pytest

import server.session as sessions


@pytest.mark.parametrize(("value", "expected"), [(None, 50), ("5", 5), ("1", 1)])
def test_session_limit_configuration(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ALIGO_MAX_SESSIONS", raising=False)
    else:
        monkeypatch.setenv("ALIGO_MAX_SESSIONS", value)
    assert sessions._configured_max_sessions() == expected


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_session_limit_rejects_invalid_configuration(monkeypatch, value):
    monkeypatch.setenv("ALIGO_MAX_SESSIONS", value)
    with pytest.raises(ValueError, match="ALIGO_MAX_SESSIONS"):
        sessions._configured_max_sessions()


def test_session_limit_evicts_oldest_idle_session(monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSIONS", 2)
    manager = sessions.SessionManager()
    manager._sessions = {
        "busy": SimpleNamespace(last_active=1, chat_lock=SimpleNamespace(locked=lambda: True)),
        "idle": SimpleNamespace(last_active=2, chat_lock=SimpleNamespace(locked=lambda: False)),
    }

    manager._evict_if_needed()

    assert set(manager._sessions) == {"busy"}


def test_session_limit_rejects_new_session_when_all_are_busy(monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSIONS", 1)
    manager = sessions.SessionManager()
    manager._sessions = {
        "busy": SimpleNamespace(last_active=1, chat_lock=SimpleNamespace(locked=lambda: True)),
    }

    with pytest.raises(RuntimeError, match="当前会话较多"):
        manager._evict_if_needed()
