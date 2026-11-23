"""已存会话查询；不会创建 Agent、修改历史或删除业务数据。"""
import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request

from context.conversation_archive import LEGACY_CONVERSATION, public_message
from context.long_term_memory import LongTermMemory, PostgresLongTermMemory
from server.auth import CurrentUser, secure_browser_transport

router = APIRouter(prefix="/api/conversations")
logger = logging.getLogger(__name__)
Cursor = Annotated[int | None, Query(ge=1, le=9_007_199_254_740_991)]


async def archive_for_user(user_id):
    from db.connection import get_pool

    pool = await get_pool()
    return PostgresLongTermMemory(user_id, pool) if pool else await asyncio.to_thread(LongTermMemory, user_id)


async def _read(request, user_id, method, *args, **kwargs):
    if not secure_browser_transport(request):
        raise HTTPException(status_code=403, detail="请通过 HTTPS 打开聊天记录。")
    try:
        archive = await archive_for_user(user_id)
        if isinstance(archive, PostgresLongTermMemory):
            return await getattr(archive, method)(*args, **kwargs)
        return await asyncio.to_thread(getattr(archive, method), *args, **kwargs)
    except Exception as exc:
        logger.warning("Conversation history unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="聊天记录暂时无法读取，请稍后重试。") from exc


@router.get("")
async def list_conversations(request: Request, owner: CurrentUser, q: Annotated[str | None, Query(max_length=100)] = None,
                             before: Cursor = None, limit: Annotated[int, Query(ge=1, le=50)] = 20):
    return await _read(request, owner, "list_conversations", query=q.strip() or None if q else None,
                       before=before, limit=limit)


@router.get("/{session_id}/messages")
async def read_conversation(
    request: Request,
    owner: CurrentUser,
    session_id: Annotated[str, Path(pattern=r"^(?:[\w-]{1,32}|~legacy)$")],
    before: Cursor = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
):
    result = await _read(request, owner, "read_conversation", session_id, before=before, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到这个会话。")
    return {"id": session_id, "readonly": session_id == LEGACY_CONVERSATION,
            "messages": [public_message(row) for row in result["rows"]], "next_before": result["next_before"]}
