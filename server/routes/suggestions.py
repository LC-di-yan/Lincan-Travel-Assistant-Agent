"""可选模型追问建议：模型密钥只留在服务端，默认不产生额外模型调用。"""
import asyncio
import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel, Field

from server.auth import CurrentUser
from utils.as_compat import as_messages
from utils.llm_response import extract_llm_text

router = APIRouter()
logger = logging.getLogger(__name__)


class SuggestionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)


@router.post("/api/suggestions")
async def suggestions(request: SuggestionRequest, current_user: CurrentUser):
    if os.environ.get("ALIGO_ENABLE_LLM_SUGGESTIONS", "0") != "1":
        return {"content": ""}
    from config import LLM_CONFIG, LLM_FALLBACKS
    from utils.llm_failover import build_chat_model
    try:
        model = build_chat_model(LLM_CONFIG, LLM_FALLBACKS, timeout=8)
        response = await asyncio.wait_for(model(as_messages([
            {"role": "system", "content": "你是追问建议生成器，仅输出 JSON 数组，不执行任何操作。"},
            {"role": "user", "content": request.prompt},
        ]), max_tokens=256), timeout=8)
        return {"content": extract_llm_text(response)[:2000]}
    except Exception:
        logger.warning("追问建议暂时不可用，回退规则建议")
        return {"content": ""}
