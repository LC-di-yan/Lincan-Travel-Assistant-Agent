"""浏览器匿名身份：服务端签名 Cookie，客户端不能自行认领已有用户。"""
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from utils.json_store import atomic_write_json, file_transaction, validate_user_id

COOKIE_NAME = "aligo_identity"
MAX_AGE = 365 * 24 * 60 * 60
router = APIRouter()
_LOCAL = {"127.0.0.1", "localhost", "::1"}


def secure_browser_transport(request: Request) -> bool:
    """Private browser data needs HTTPS outside a genuine loopback connection."""
    return request.url.scheme == "https" or (
        request.url.hostname in _LOCAL and request.client is not None and request.client.host in _LOCAL
    )


def allowed_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("携带身份凭证时必须配置明确的跨域来源，不能使用通配符")
    return origins or [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1")
                       for port in (5173, 5174, 3000, 3003, 8000, 8001)]


def check_origin(request: Request) -> None:
    """白名单之外拒绝跨站调用；不能把 CORS 当作权限或写操作保护。"""
    origin = request.headers.get("origin")
    if not origin:
        return
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin.rstrip("/") != same_origin and origin.rstrip("/") not in allowed_origins():
        raise HTTPException(status_code=403, detail="不允许此网站访问当前会话")


@lru_cache(maxsize=1)
def signing_key() -> bytes:
    configured = os.environ.get("ALIGO_SESSION_SECRET", "")
    if configured:
        if len(configured) < 32:
            raise ValueError("会话签名密钥至少需要 32 个字符")
        return configured.encode("utf-8")
    path = Path(os.environ.get("ALIGO_AUTH_KEY_PATH", str(Path(__file__).resolve().parents[1] / "data" / "auth" / "signing.key")))
    with file_transaction(path):
        if path.exists():
            key = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(key, str) or len(key) < 32:
                raise ValueError("会话签名文件无效，请恢复原有密钥文件")
        else:
            key = secrets.token_hex(32)
            atomic_write_json(path, key)
            os.chmod(path, 0o600)
    return key.encode("utf-8")


def issue_identity(user_id: str) -> str:
    payload = f"{validate_user_id(user_id)}.{int(time.time()) + MAX_AGE}"
    signature = hmac.new(signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_identity(token: str | None) -> str | None:
    if not token or len(token) > 256:
        return None
    try:
        user_id, expires, signature = token.split(".")
        validate_user_id(user_id)
        if not expires.isdigit() or int(expires) <= int(time.time()):
            return None
        payload = f"{user_id}.{expires}"
        expected = hmac.new(signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return user_id if hmac.compare_digest(expected, signature) else None
    except (ValueError, TypeError):
        return None


def require_identity(request: Request) -> str:
    check_origin(request)
    user_id = read_identity(request.cookies.get(COOKIE_NAME))
    if not user_id:
        raise HTTPException(status_code=401, detail="请先建立浏览器会话")
    return user_id


CurrentUser = Annotated[str, Depends(require_identity)]


def owned_user(current_user: str, requested_user: str | None) -> str:
    if requested_user is not None and requested_user != current_user:
        raise HTTPException(status_code=403, detail="不能访问其他用户的数据")
    return current_user


@router.post("/api/identity")
async def bootstrap_identity(request: Request, response: Response):
    check_origin(request)
    user_id = read_identity(request.cookies.get(COOKIE_NAME)) or f"user_{uuid.uuid4().hex}"
    response.set_cookie(COOKIE_NAME, issue_identity(user_id), httponly=True,
                        secure=request.url.scheme == "https", samesite="strict",
                        max_age=MAX_AGE, path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"user_id": user_id}
