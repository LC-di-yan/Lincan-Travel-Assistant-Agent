import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from utils.as_compat import mk_msg, msg_json, msg_text


@pytest.fixture
def itinerary_agent_class():
    path = Path(__file__).resolve().parents[1] / ".claude/skills/plan-trip/script/agent.py"
    spec = importlib.util.spec_from_file_location("test_itinerary_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ItineraryPlanningAgent


def response(text):
    return SimpleNamespace(text=text, content=[] if not text else [{"type": "text", "text": text}])


def request():
    return mk_msg("user", {"context": {"rewritten_query": "明天从北京去上海出差3天", "duration_days": 3}}, role="user")


def test_empty_structured_message_payload_still_round_trips():
    assert json.loads(msg_text(mk_msg("user", []))) == []


@pytest.mark.asyncio
async def test_itinerary_disables_thinking_with_supported_glm_parameter(itinerary_agent_class):
    model = AsyncMock(return_value=response(json.dumps({"itinerary": {"daily_plans": []}, "planning_complete": True})))
    result = msg_json(await itinerary_agent_class(model=model).reply(request()))

    assert result["planning_complete"] is True
    assert model.await_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_itinerary_retries_without_thinking_option_when_rejected(itinerary_agent_class):
    model = AsyncMock(side_effect=[ValueError("unsupported parameter thinking"), response('{"itinerary": {"daily_plans": []}}')])
    result = msg_json(await itinerary_agent_class(model=model).reply(request()))

    assert "error" not in result
    assert model.await_count == 2
    assert "extra_body" not in model.await_args_list[1].kwargs


@pytest.mark.asyncio
async def test_itinerary_explains_empty_model_output(itinerary_agent_class):
    model = AsyncMock(return_value=response(""))
    result = msg_json(await itinerary_agent_class(model=model).reply(request()))

    assert result["planning_complete"] is False
    assert result["error_code"] == "empty_response"
    assert "没有返回有效的行程内容" in result["error"]


@pytest.mark.parametrize("override", ["", "glm-5.3-flash"])
def test_only_legacy_itinerary_uses_the_optional_model_override(tmp_path, monkeypatch, override):
    import config
    from agents.lazy_agent_registry import LazyAgentRegistry

    primary, planner = object(), object()
    factory = Mock(return_value=planner)
    primary_config = {**config.LLM_CONFIG, "model_name": "deepseek-v4.1-flash-261017"}
    monkeypatch.setattr(config, "LLM_CONFIG", primary_config)
    monkeypatch.setattr(config, "ITINERARY_MODEL_NAME", override)
    monkeypatch.setattr("utils.llm_failover.build_chat_model", factory)
    monkeypatch.setattr(LazyAgentRegistry, "CONFIG_PATH", tmp_path / "plugins.json")
    registry = LazyAgentRegistry(model=primary, cache={})

    assert registry["translation"].model is primary
    itinerary = registry["itinerary_planning"]
    assert itinerary.model is (planner if override else primary)
    assert registry["itinerary_planning"] is itinerary
    if override:
        factory.assert_called_once_with({**primary_config, "model_name": override}, config.LLM_FALLBACKS,
                                        timeout=float(config.SYSTEM_CONFIG.get("timeout", 60)))
    else:
        factory.assert_not_called()
