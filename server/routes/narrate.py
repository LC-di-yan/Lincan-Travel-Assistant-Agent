"""Narration SSE 端点

调 GLM-5.2（思考模型）流式生成播报文案，仅透传 content（跳过 reasoning_content）。
前端拿到完整文案后调 /api/tts 朗读。

- 完成播报：Agent 结果就绪后，用角色口吻讲结果
- 独立熔断器，与 chat / TTS 隔离
"""
import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import NARRATION_CONFIG
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from server.routes.tts_personas import (
    get_persona,
    get_narration_instruction,
    get_progress_text,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Narration 独立熔断器（与 chat / TTS 隔离）
_narration_circuit = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout_sec=60.0,
    half_open_successes=2,
)


class NarrateRequest(BaseModel):
    intention: Optional[str] = None
    result_data: Any = None  # Agent 结果（dict / list / str 均可）
    persona_id: Optional[str] = None


def _truncate_result(data: Any, max_chars: int = 1200) -> str:
    """把 result_data 序列化为紧凑 JSON，超长截断。

    narration 不需要完整数据，关键信息够 LLM 写文案即可。
    """
    try:
        s = json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        s = str(data)
    if len(s) > max_chars:
        s = s[:max_chars] + "...(已截断)"
    return s


def _build_messages(
    persona_base_prompt: str,
    narration_instruction: str,
    result_json: str,
) -> list[dict]:
    """构造 GLM 请求的 messages。"""
    system_prompt = (
        f"{persona_base_prompt}\n\n"
        "【任务】用你的语气给用户汇报以下结果，自然口语，像朋友聊天。\n"
        "简短思考后直接输出文案，不要过度分析。\n"
        f"【汇报要求】\n{narration_instruction}\n\n"
        "【通用约束】\n"
        "- 80-150字\n"
        "- 第一人称\n"
        "- 不要说'已为您'这种官方话术\n"
        "- 不要念 JSON 字段名或 key\n"
        "- 直接输出文案，不要解释、不要前缀\n"
    )
    user_prompt = f"【结果数据】\n{result_json}\n\n直接输出播报文案："
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _stream_glm(
    messages: list[dict],
) -> AsyncIterator[dict]:
    """流式调 GLM-5.2，仅透传 content（跳过 reasoning_content）。"""
    if not NARRATION_CONFIG["api_key"]:
        logger.error("[Narration] NARRATION_API_KEY not configured")
        yield {
            "event": "error",
            "data": json.dumps(
                {"message": "播报服务未配置 API Key"},
                ensure_ascii=False,
            ),
        }
        return

    payload = {
        "model": NARRATION_CONFIG["model"],
        "messages": messages,
        "max_tokens": NARRATION_CONFIG["max_tokens"],
        "temperature": NARRATION_CONFIG["temperature"],
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {NARRATION_CONFIG['api_key']}",
        "Content-Type": "application/json",
    }
    url = f"{NARRATION_CONFIG['base_url']}/chat/completions"
    timeout = httpx.Timeout(
        NARRATION_CONFIG["timeout_sec"],
        connect=NARRATION_CONFIG["connect_timeout_sec"],
    )

    content_started = False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.error(f"[Narration] upstream {resp.status_code}: {body[:300]}")
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"message": f"播报服务异常 (HTTP {resp.status_code})"},
                            ensure_ascii=False,
                        ),
                    }
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}) or {}
                    # 仅透传 content，跳过 reasoning_content（思考阶段不输出给前端）
                    content = delta.get("content")
                    if content:
                        content_started = True
                        yield {
                            "event": "delta",
                            "data": json.dumps(
                                {"text": content},
                                ensure_ascii=False,
                            ),
                        }
    except httpx.HTTPError as e:
        logger.exception("[Narration] upstream connection failed")
        yield {
            "event": "error",
            "data": json.dumps(
                {"message": f"播报连接失败: {e}"},
                ensure_ascii=False,
            ),
        }
        return

    if not content_started:
        # 思考阶段耗尽 max_tokens，正式文案一个字没出
        logger.warning("[Narration] no content produced (reasoning exhausted max_tokens?)")
        yield {
            "event": "error",
            "data": json.dumps(
                {"message": "播报生成失败（思考超时）"},
                ensure_ascii=False,
            ),
        }
        return

    yield {"event": "done", "data": "{}"}


@router.post("/api/narrate")
async def narrate(req: NarrateRequest):
    """流式生成播报文案，返回 SSE 事件流。"""
    try:
        _narration_circuit.raise_if_open()
    except CircuitOpenError:
        async def _blocked():
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": "播报服务暂时不可用，请稍后再试"},
                    ensure_ascii=False,
                ),
            }
        return EventSourceResponse(_blocked())

    persona = get_persona(req.persona_id)
    narration_instruction = get_narration_instruction(req.intention)
    result_json = _truncate_result(req.result_data)
    messages = _build_messages(persona.base_prompt, narration_instruction, result_json)

    async def _generator():
        try:
            async for evt in _stream_glm(messages):
                yield evt
            _narration_circuit.record_success()
        except Exception as e:
            _narration_circuit.record_failure()
            logger.exception("[Narration] generator failed")
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": f"播报内部错误: {e}"},
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(_generator())


class ProgressRequest(BaseModel):
    milestone: str  # thinking / skill_selected / skill_executing / skill_complete
    skill: Optional[str] = None  # agent_name 或 intention type
    context: Optional[dict] = None  # 附加上下文（用户消息等）
    persona_id: Optional[str] = None


async def _generate_progress_via_llm(
    persona_base_prompt: str,
    milestone: str,
    skill: Optional[str],
    context: Optional[dict],
) -> Optional[str]:
    """LLM 兜底生成进度文案（max_tokens=80，超时 5s）。"""
    skill_desc = {
        "itinerary_planning": "排行程",
        "place-search": "查地点",
        "hotel_search": "查酒店",
        "restaurant_search": "查餐厅",
        "scenic_search": "查景点",
        "information_query": "查信息",
        "rag_knowledge": "查知识",
        "expense_tracking": "记账",
        "translation": "翻译",
        "train_ticket": "查车票",
        "preference": "记偏好",
        "memory_query": "查记忆",
    }.get(skill or "", "处理")

    milestone_desc = {
        "thinking": f"正在思考用户需求",
        "skill_selected": f"准备开始{skill_desc}",
        "skill_executing": f"正在{skill_desc}",
        "skill_complete": f"{skill_desc}完成",
    }.get(milestone, "处理中")

    user_msg = f"用一句话（10字内）表达'已完成：{milestone_desc}'，符合你的角色语气。直接输出文案，不要解释。"
    messages = [
        {"role": "system", "content": f"{persona_base_prompt}\n\n用极简短的话汇报进度，10字内，符合角色语气。直接输出文案。"},
        {"role": "user", "content": user_msg},
    ]

    payload = {
        "model": NARRATION_CONFIG["model"],
        "messages": messages,
        "max_tokens": 400,  # 思考阶段约 200-300 tokens，正式文案 10-30 tokens
        "temperature": 0.7,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {NARRATION_CONFIG['api_key']}",
        "Content-Type": "application/json",
    }
    url = f"{NARRATION_CONFIG['base_url']}/chat/completions"
    timeout = httpx.Timeout(8.0, connect=3.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.warning(f"[Narration/Progress] LLM {resp.status_code}")
                return None
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
            return content.strip() if content else None
    except Exception:
        logger.exception("[Narration/Progress] LLM fallback failed")
        return None


@router.post("/api/narrate/progress")
async def narrate_progress(req: ProgressRequest):
    """进度播报：模板优先（0 延迟），LLM 兜底。非流式短文案。"""
    # 模板优先
    text = get_progress_text(req.persona_id, req.milestone, req.skill)
    if text:
        return {"text": text, "source": "template"}

    # LLM 兜底（仅在模板未命中时）
    try:
        _narration_circuit.raise_if_open()
    except CircuitOpenError:
        return {"text": "", "source": "circuit_open"}

    persona = get_persona(req.persona_id)
    llm_text = await _generate_progress_via_llm(
        persona.base_prompt, req.milestone, req.skill, req.context
    )
    if llm_text:
        _narration_circuit.record_success()
        return {"text": llm_text, "source": "llm"}

    _narration_circuit.record_failure()
    return {"text": "", "source": "failed"}
