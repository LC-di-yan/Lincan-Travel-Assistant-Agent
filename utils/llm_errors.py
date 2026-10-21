"""LLM 上游错误分类 + 用户友好文案

背景（2026-10-20）：
    maas.qianwenaiapi.com 的 workspace key 从 09:55 起对**所有模型**返回
    403 AccessDenied.Unpurchased。原始异常文本（含 JSON 错误体）被
    plan-trip 直接拼进 result["error"]，再经 assistant_summary 写进
    记忆和前端，用户看到一大段 `Error code: 403 - {...}`。

本模块把上游异常收敛成：
    1. 稳定的错误码（写日志 / 前端埋点用）
    2. 一句中文人话（给用户看，不含上游 URL、key、JSON）

注意：不要把异常原文放进 friendly()，那是给用户看的。
"""
from __future__ import annotations

import re
from typing import Optional

# 错误码 -> 中文人话
_MESSAGES = {
    "entitlement": "模型服务对该账号未授权或额度已用尽",
    "arrears": "模型服务账号欠费，结清后才能继续使用",
    "auth": "模型 API Key 无效或已过期",
    "rate_limit": "模型服务请求过于频繁，被限流",
    "timeout": "模型服务响应超时",
    "upstream": "模型服务暂时不可用",
    "bad_request": "模型服务拒绝了本次请求",
    "parse": "模型返回的内容无法解析",
    "unknown": "模型服务异常",
}


def status_code(exc: BaseException) -> Optional[int]:
    """尽量从异常里取出 HTTP 状态码（兼容 openai / httpx / agentscope）。"""
    for attr in ("status_code", "status", "http_status"):
        code = getattr(exc, attr, None)
        if isinstance(code, int):
            return code

    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    if isinstance(code, int):
        return code

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        code = body.get("code")
        if isinstance(code, int):
            return code

    # openai SDK 的异常文本形如 "Error code: 403 - {...}"
    m = re.search(r"Error code:\s*(\d{3})", str(exc))
    if m:
        return int(m.group(1))
    return None


def upstream_code(exc: BaseException) -> str:
    """上游业务错误码，例如 AccessDenied.Unpurchased / invalid_api_key。"""
    text = str(exc)
    m = re.search(r"'code':\s*'([^']+)'", text) or re.search(r'"code"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r"'type':\s*'([^']+)'", text)
    if m:
        return m.group(1)
    return ""


def classify(exc: BaseException, stage: str = "") -> str:
    """异常 -> 错误码。

    stage: "parse" 表示调用已经成功、只是解析失败（不重试通道）。
    """
    if stage == "parse":
        return "parse"

    text = str(exc).lower()
    code = status_code(exc)

    # 阿里云百炼欠费的原始错误：type/code = Arrearage，"not in good standing" / overdue-payment
    # 中转站通常只透出 403 Unpurchased，看不出是欠费，所以优先按文案识别。
    if "arrearage" in text or "overdue-payment" in text or "not in good standing" in text:
        return "arrears"
    if code == 403 or "unpurchased" in text or "access denied" in text:
        return "entitlement"
    if code in (401, 402) or "authentication" in text or "invalid_api_key" in text:
        return "auth"
    if code == 429 or "rate limit" in text or "too many requests" in text:
        return "rate_limit"
    if code == 408 or "timeout" in text or "timed out" in text:
        return "timeout"
    if code is not None and 500 <= code <= 599:
        return "upstream"
    if code in (400, 404, 422):
        # 404 = 该通道没有这个模型；400/422 = 参数不被接受
        return "bad_request"
    return "unknown"


def friendly(exc: BaseException = None, code: str = "") -> str:
    """给用户看的一句话（不含上游细节）。"""
    if not code and exc is not None:
        code = classify(exc)
    return _MESSAGES.get(code or "unknown", _MESSAGES["unknown"])


def friendly_text(text: str, default: str = "") -> str:
    """只有错误字符串、没有异常对象时用（例如存进 last_error_msg 的文本）。

    2026-10-20 侧栏 REASONING 泄漏：
        「意图识别出错，使用默认策略。错误: Error code: 403 - {...}」
    """
    if not (text or "").strip():
        return default or _MESSAGES["unknown"]
    return friendly(Exception(text))



def describe(exc: BaseException) -> str:
    """给日志看的一句话：状态码 + 上游业务码 + 原文截断。"""
    code = classify(exc)
    sc = status_code(exc)
    ucode = upstream_code(exc)
    head = f"class={code}"
    if sc:
        head += f" http={sc}"
    if ucode:
        head += f" upstream={ucode}"
    return f"{head} raw={str(exc)[:300]}"
