"""Local OpenAI-compatible mock for TTS / narration integration tests.

Run:
    .venv\\Scripts\\python.exe -m uvicorn tests.mock_audio_provider:app --port 3015
"""
import asyncio
import base64
import json
import math
import struct

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

SAMPLE_RATE = 24000
DURATION_SEC = 1.2


def _pcm_chunks() -> list[str]:
    total = int(SAMPLE_RATE * DURATION_SEC)
    pcm = bytearray()
    for i in range(total):
        sample = int(0.18 * 32767 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE))
        pcm += struct.pack("<h", sample)
    step = 4800  # 0.1 s at 24 kHz mono PCM16
    return [base64.b64encode(bytes(pcm[i:i + step])).decode("ascii") for i in range(0, len(pcm), step)]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    is_tts = bool(body.get("audio"))

    async def tts_stream():
        for chunk in _pcm_chunks():
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"audio": {"data": chunk}}}]},
                ensure_ascii=False,
            ) + "\n\n"
            await asyncio.sleep(0.01)
        yield "data: [DONE]\n\n"

    async def narrate_stream():
        for piece in ("这是自动化测试播报，", "音频链路正常。"):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": piece}}]},
                ensure_ascii=False,
            ) + "\n\n"
            await asyncio.sleep(0.02)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        tts_stream() if is_tts else narrate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
