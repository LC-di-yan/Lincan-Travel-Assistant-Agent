"""
LLM 响应提取工具
统一提取 ChatResponse / dict 中的文本内容
"""
import json
import logging
from typing import Any, Optional
from utils.json_parser import robust_json_parse

logger = logging.getLogger(__name__)


def _safe_hasattr(obj, attr):
    """hasattr 安全版：ChatResponse 的 __getattr__ 会抛 KeyError"""
    try:
        return hasattr(obj, attr)
    except (KeyError, AttributeError, TypeError):
        return False


def extract_llm_text(response: Any, fallback: str = "") -> str:
    """
    从 LLM 响应中提取纯文本（非流式，直接取 .text / .content）。

    兼容：
    - response.text / response.content（ChatResponse / dict）
    - 空列表、空字符串、thinking-only 响应 → 返回 fallback
    """
    if response is None:
        return fallback

    try:
        if _safe_hasattr(response, 'text'):
            t = response.text
            if t and t.strip():
                return t
            # .text 为空，尝试 .content
        if _safe_hasattr(response, 'content'):
            c = response.content
            if isinstance(c, str):
                return c if c.strip() else fallback
            if isinstance(c, list):
                # 过滤 thinking 块，只取 text 块
                parts = []
                for item in c:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        t = item.get('text', '')
                        if t and t.strip():
                            parts.append(t)
                if parts:
                    return ''.join(parts)
                # MiMo 有时只返回 thinking 块不返回 text 块
                return fallback
            if c is None:
                return fallback
            return str(c)
        if isinstance(response, dict):
            c = response.get('content') or response.get('text', '')
            if isinstance(c, str) and c.strip():
                return c
            return fallback
        s = str(response)
        return s if s.strip() and s != 'None' else fallback
    except Exception:
        return fallback


def strip_markdown_fences(text: str) -> str:
    """去除 ```json ... ``` 包裹"""
    text = text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    return text.strip()


def extract_json_object(text: str) -> Optional[dict]:
    """从文本中提取第一个 JSON 对象（去掉 markdown 围栏后），使用健壮解析"""
    if not text or not text.strip():
        return None
    cleaned = strip_markdown_fences(text)
    try:
        return robust_json_parse(cleaned, fallback=None)
    except (ValueError, UnboundLocalError):
        return None


def extract_llm_json(response: Any, fallback: Optional[dict] = None) -> dict:
    """
    一步完成：提取文本 → 去围栏 → 解析 JSON。

    Args:
        response: LLM 原始返回
        fallback: 解析失败时的默认值

    Returns:
        解析后的 dict，失败返回 fallback
    """
    text = extract_llm_text(response)
    if not text or not text.strip():
        logger.warning("Empty LLM response text, using fallback")
        return fallback if fallback is not None else {"error": "empty_response"}
    result = extract_json_object(text)
    if result is not None:
        return result
    logger.error(f"No JSON found in LLM response. Text: {text[:500]}")
    return fallback if fallback is not None else {"error": "parse_failed", "raw": text[:500]}
