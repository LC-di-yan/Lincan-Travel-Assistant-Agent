"""个人中心特性开关、站点约束及表单校验。"""
import hashlib
import hmac
import os
from urllib.parse import urlsplit

from fastapi import Request

from server.auth import allowed_origins, secure_browser_transport, signing_key
from server.personal.service import PersonalError

_LOCAL = {"127.0.0.1", "localhost", "::1"}


def personal_enabled() -> bool:
    return os.getenv("ALIGO_PERSONAL_CENTER_ENABLED", "0").strip().lower() in {"1", "true", "on"}


def secure_personal_site(request: Request) -> bool:
    return secure_browser_transport(request)


def csrf_for(user_id: str) -> str:
    return hmac.new(signing_key(), f"aligo:personal:csrf:v1:{user_id}".encode(), hashlib.sha256).hexdigest()


def check_personal_write(request: Request, user_id: str) -> None:
    origin = request.headers.get("origin")
    if not origin and (ref := request.headers.get("referer")):
        try:
            parts = urlsplit(ref)
            origin = f"{parts.scheme}://{parts.netloc}"
        except ValueError:
            origin = None
    expected = f"{request.url.scheme}://{request.url.netloc}"
    is_local_proxy = request.url.hostname in _LOCAL and origin in allowed_origins() and urlsplit(origin).hostname in _LOCAL
    if origin != expected and not is_local_proxy:
        raise PersonalError(403, "untrusted_origin", "请从当前站点提交个人行程操作。")
    token = request.headers.get("x-aligo-csrf", "")
    if not token.isascii() or len(token) != 64 or not hmac.compare_digest(token, csrf_for(user_id)):
        raise PersonalError(403, "invalid_csrf", "表单已失效，请刷新后再试。")
