"""TTS SSE 流式端点

调用小米 MiMo `mimo-v2.5-tts` 模型，流式返回 PCM16 音频块。
关键点：
- 认证头用 `api-key`（非 `Authorization`），需用 httpx 直发请求
- 返回裸 PCM16（无 WAV 头），前端按 24kHz 单声道处理
- 上游 SSE 结构：choices[0].delta.audio.data（base64），末尾 [DONE]
- 角色化音色：persona = voice + 基础人设指令；scene = 按意图叠加
"""
import json
import logging
import re
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import TTS_CONFIG
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from server.routes.tts_personas import get_persona, build_style, get_persona_meta

logger = logging.getLogger(__name__)
router = APIRouter()

# TTS 专用熔断器（与 chat 的熔断器隔离，避免 TTS 失败影响主对话）
_tts_circuit = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout_sec=60.0,
    half_open_successes=2,
)


class TTSRequest(BaseModel):
    text: str
    # persona_id 优先；voice/style 为兼容旧前端保留
    persona_id: Optional[str] = None
    voice: Optional[str] = None
    style: Optional[str] = None
    intention: Optional[str] = None


@router.get("/api/tts/personas")
async def list_personas():
    """返回可用角色列表，供前端渲染音色选择 UI。"""
    return {"personas": get_persona_meta()}


def _preprocess_text(text: str) -> str:
    """文本预处理。

    MiMo 会根据标点自然停顿，不需要额外注入标签。
    文档里的 [吸气] [深呼吸] 等是有效音频标签，但 [停顿] 不是——
    会被当普通文字念出来。这里只做轻度清理：
    - 合并连续空白为单个空格
    - 保留换行（MiMo 会处理段落停顿）
    """
    if not text:
        return text
    # 合并连续空格（不含换行）
    processed = re.sub(r"[^\S\n]+", " ", text)
    return processed


def _resolve_payload(req: TTSRequest) -> tuple[str, str, str]:
    """解析请求 → (text, voice, style)。

    优先级：persona_id > voice/style 显式指定 > 默认角色。
    """
    text = _preprocess_text(req.text)

    if req.persona_id:
        persona = get_persona(req.persona_id)
        voice = persona.voice
        style = build_style(persona, req.intention)
        return text, voice, style

    # 兼容旧前端：显式 voice/style
    if req.voice or req.style:
        voice = req.voice or TTS_CONFIG["default_voice"]
        style = req.style or TTS_CONFIG["default_style"]
        return text, voice, style

    # 默认用第一个角色（小冰）
    persona = get_persona(None)
    voice = persona.voice
    style = build_style(persona, req.intention)
    return text, voice, style


async def _stream_mimo(
    text: str,
    voice: str,
    style: str,
) -> AsyncIterator[dict]:
    """流式调用 MiMo TTS，按 chunk 透传给前端。"""
    if not TTS_CONFIG["api_key"]:
        logger.error("[TTS] MIMO_API_KEY not configured")
        yield {"event": "error", "data": json.dumps({"message": "TTS 服务未配置 API Key"}, ensure_ascii=False)}
        return

    payload = {
        "model": TTS_CONFIG["model"],
        "messages": [
            {"role": "user", "content": style},
            {"role": "assistant", "content": text},
        ],
        "audio": {"format": "pcm16", "voice": voice},
        "stream": True,
    }
    headers = {
        "api-key": TTS_CONFIG["api_key"],
        "Content-Type": "application/json",
    }
    url = f"{TTS_CONFIG['base_url']}/chat/completions"
    timeout = httpx.Timeout(
        TTS_CONFIG["timeout_sec"],
        connect=TTS_CONFIG["connect_timeout_sec"],
    )

    idx = 0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.error(f"[TTS] upstream {resp.status_code}: {body[:300]}")
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"message": f"TTS 服务异常 (HTTP {resp.status_code})"},
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
                    audio = delta.get("audio")
                    if audio and audio.get("data"):
                        yield {
                            "event": "audio",
                            "data": json.dumps(
                                {"chunk": audio["data"], "index": idx},
                                ensure_ascii=False,
                            ),
                        }
                        idx += 1
    except httpx.HTTPError as e:
        logger.exception("[TTS] upstream connection failed")
        yield {
            "event": "error",
            "data": json.dumps(
                {"message": f"TTS 连接失败: {e}"},
                ensure_ascii=False,
            ),
        }
        return

    yield {"event": "done", "data": "{}"}


@router.post("/api/tts")
async def tts(req: TTSRequest):
    """流式合成语音，返回 SSE 事件流。"""
    # 熔断检查
    try:
        _tts_circuit.raise_if_open()
    except CircuitOpenError:
        async def _blocked():
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": "TTS 服务暂时不可用，请稍后再试"},
                    ensure_ascii=False,
                ),
            }
        return EventSourceResponse(_blocked())

    text, voice, style = _resolve_payload(req)

    async def _generator():
        try:
            async for evt in _stream_mimo(text, voice, style):
                yield evt
            _tts_circuit.record_success()
        except Exception as e:
            _tts_circuit.record_failure()
            logger.exception("[TTS] generator failed")
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": f"TTS 内部错误: {e}"},
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(_generator())
