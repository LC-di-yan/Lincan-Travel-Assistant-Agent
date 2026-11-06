import asyncio, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()

from config import LLM_CONFIG
from utils.as_compat import as_messages, build_chat_model, msg_text

PROMPT = "判断这句话的意图，只输出JSON：{<<< 帮我订杭州西湖边的酒店 >>>} 字段：intents(数组,每项含type)"

async def try_mode(label, extra):
    model = build_chat_model({
        "model_name": LLM_CONFIG["model_name"],
        "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"],
        "generate_kwargs": {"temperature": 0, "max_tokens": 200},
    })
    try:
        resp = await model(as_messages([{"role": "user", "content": PROMPT}]), **extra)
        text = msg_text(resp)
        ok = False
        try:
            json.loads(text)
            ok = True
        except Exception:
            ok = False
        print(f"[{label}] len={len(text)} valid_json={ok} head={text[:90]!r}")
    except Exception as e:
        print(f"[{label}] FAILED: {type(e).__name__}: {str(e)[:200]}")

async def main():
    await try_mode("baseline", {})
    await try_mode("json_object", {"response_format": {"type": "json_object"}})

asyncio.run(main())
