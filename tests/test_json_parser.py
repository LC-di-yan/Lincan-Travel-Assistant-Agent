"""Tests for utils/json_parser.py"""
import pytest
from utils.json_parser import robust_json_parse


class TestRobustJsonParse:
    """Test robust_json_parse with various edge cases"""

    def test_valid_json(self):
        text = '{"key": "value", "num": 42}'
        result = robust_json_parse(text)
        assert result == {"key": "value", "num": 42}

    def test_json_in_markdown_fence(self):
        text = '```json\n{"a": 1}\n```'
        result = robust_json_parse(text)
        assert result == {"a": 1}

    def test_json_with_surrounding_text(self):
        text = 'Here is the answer: {"result": "ok"} and more text'
        result = robust_json_parse(text)
        assert result == {"result": "ok"}

    def test_empty_text_with_fallback(self):
        result = robust_json_parse("", fallback={"default": True})
        assert result == {"default": True}

    def test_empty_text_without_fallback(self):
        with pytest.raises(ValueError):
            robust_json_parse("")

    def test_no_json_with_fallback(self):
        result = robust_json_parse("no json here", fallback={})
        assert result == {}

    def test_no_json_without_fallback(self):
        with pytest.raises(ValueError):
            robust_json_parse("no json here")

    def test_trailing_comma_in_object(self):
        text = '{"a": 1, "b": 2,}'
        result = robust_json_parse(text)
        assert result == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        text = '{"items": [1, 2, 3,]}'
        result = robust_json_parse(text)
        assert result == {"items": [1, 2, 3]}

    def test_chinese_quotes(self):
        text = '{"key": "value"}'
        result = robust_json_parse(text)
        assert result == {"key": "value"}

    def test_already_dict(self):
        d = {"already": "dict"}
        result = robust_json_parse(d)
        assert result == d

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = robust_json_parse(text)
        assert result == {"outer": {"inner": [1, 2, 3]}}
