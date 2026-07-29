"""Tests for IntentionAgent retry and fallback behavior (no real LLM calls)."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.intention_agent import IntentionAgent
from agentscope.message import Msg


class FakeModel:
    """Configurable async model for testing."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    async def __call__(self, messages):
        if self.call_count >= len(self.responses):
            raise RuntimeError("No more mocked responses")
        response = self.responses[self.call_count]
        self.call_count += 1
        if isinstance(response, BaseException):
            raise response
        return response


def _make_response(text):
    resp = MagicMock()
    resp.text = text
    return resp


@pytest.fixture
def agent_factory():
    """Factory that creates an IntentionAgent with a patched SkillLoader."""

    def _make(responses):
        dummy_model = AsyncMock()
        agent = IntentionAgent(name="TestAgent", model=dummy_model)
        agent.model = FakeModel(responses)
        # Bypass real SkillLoader filesystem reads
        agent.skill_loader = MagicMock()
        agent.skill_loader.get_skill_prompt.return_value = "mock skills"
        return agent

    return _make


class TestIntentionAgentRetry:
    async def _call(self, agent, query="hello"):
        msg = Msg(name="User", content=query, role="user")
        return await agent.reply(msg)

    def test_valid_response_parsed(self, agent_factory):
        agent = agent_factory([_make_response('{"intents": [{"type": "event_collection"}]}')])
        result = asyncio.run(self._call(agent))
        data = json.loads(result.content)
        assert data["intents"][0]["type"] == "event_collection"
        assert agent.model.call_count == 1

    def test_json_parse_failure_then_success(self, agent_factory):
        agent = agent_factory([
            _make_response("not json"),
            _make_response('{"intents": [{"type": "itinerary_planning"}]}'),
        ])
        result = asyncio.run(self._call(agent))
        data = json.loads(result.content)
        assert data["intents"][0]["type"] == "itinerary_planning"
        assert agent.model.call_count == 2

    def test_two_json_parse_failures_return_default(self, agent_factory):
        agent = agent_factory([
            _make_response("not json"),
            _make_response("still not json"),
        ])
        result = asyncio.run(self._call(agent))
        data = json.loads(result.content)
        assert data["intents"][0]["type"] == "information_query"
        assert "JSON解析失败" in data["reasoning"]
        assert agent.model.call_count == 2

    def test_exception_then_success(self, agent_factory):
        agent = agent_factory([
            RuntimeError("boom"),
            _make_response('{"intents": [{"type": "memory_query"}]}'),
        ])
        result = asyncio.run(self._call(agent))
        data = json.loads(result.content)
        assert data["intents"][0]["type"] == "memory_query"
        assert agent.model.call_count == 2

    def test_two_exceptions_return_default(self, agent_factory):
        agent = agent_factory([
            UnboundLocalError("cannot access local variable 'e'"),
            RuntimeError("boom again"),
        ])
        result = asyncio.run(self._call(agent))
        data = json.loads(result.content)
        assert data["intents"][0]["type"] == "information_query"
        assert "boom again" in data["reasoning"]
        assert agent.model.call_count == 2

    def test_empty_input_returns_empty_json(self, agent_factory):
        agent = agent_factory([])
        result = asyncio.run(agent.reply(None))
        assert result.content == "{}"
