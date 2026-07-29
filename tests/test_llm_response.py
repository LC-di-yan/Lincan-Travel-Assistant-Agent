"""Tests for utils/llm_response.py"""
import pytest
from utils.llm_response import (
    extract_llm_text,
    strip_markdown_fences,
    extract_json_object,
    extract_llm_json,
)


_sentinel = object()


class FakeResponse:
    """Simple fake response for testing"""
    def __init__(self, text=_sentinel, content=_sentinel):
        if text is not _sentinel:
            self.text = text
        if content is not _sentinel:
            self.content = content


class TestExtractLlmText:
    """Test extract_llm_text"""

    def test_none_returns_fallback(self):
        result = extract_llm_text(None)
        assert result == ""

    def test_none_returns_custom_fallback(self):
        result = extract_llm_text(None, fallback="N/A")
        assert result == "N/A"

    def test_text_attribute(self):
        resp = FakeResponse(text="hello world")
        result = extract_llm_text(resp)
        assert result == "hello world"

    def test_content_attribute_string(self):
        class ContentOnly:
            content = "test content"
        resp = ContentOnly()
        result = extract_llm_text(resp)
        assert result == "test content"

    def test_dict_with_content(self):
        resp = {"content": "from dict"}
        result = extract_llm_text(resp)
        assert result == "from dict"

    def test_plain_string(self):
        result = extract_llm_text("plain string")
        assert result == "plain string"


class TestStripMarkdownFences:
    """Test strip_markdown_fences"""

    def test_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_plain_fence(self):
        text = '```\nsome code\n```'
        assert strip_markdown_fences(text) == 'some code'

    def test_no_fence(self):
        text = '{"key": "value"}'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_strips_whitespace(self):
        text = '  ```json\n{"a": 1}\n```  '
        assert strip_markdown_fences(text) == '{"a": 1}'


class TestExtractJsonObject:
    """Test extract_json_object"""

    def test_simple_json(self):
        text = '{"key": "value"}'
        result = extract_json_object(text)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result: {"key": "value"} done.'
        result = extract_json_object(text)
        assert result == {"key": "value"}

    def test_json_in_fence(self):
        text = '```json\n{"a": 1}\n```'
        result = extract_json_object(text)
        assert result == {"a": 1}

    def test_no_json_returns_none(self):
        text = "no json here"
        result = extract_json_object(text)
        assert result is None

    def test_nested_json(self):
        text = '{"outer": {"inner": 42}}'
        result = extract_json_object(text)
        assert result == {"outer": {"inner": 42}}


class TestExtractLlmJson:
    """Test extract_llm_json"""

    def test_valid_json(self):
        resp = FakeResponse(text='{"action": "test"}')
        result = extract_llm_json(resp)
        assert result == {"action": "test"}

    def test_json_in_fence(self):
        resp = FakeResponse(text='```json\n{"key": "val"}\n```')
        result = extract_llm_json(resp)
        assert result == {"key": "val"}

    def test_no_json_returns_fallback(self):
        resp = FakeResponse(text="no json here")
        fallback = {"default": True}
        result = extract_llm_json(resp, fallback=fallback)
        assert result == fallback

    def test_no_json_default_fallback(self):
        resp = FakeResponse(text="no json")
        result = extract_llm_json(resp)
        assert "error" in result
