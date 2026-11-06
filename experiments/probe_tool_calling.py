import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
from config import LLM_CONFIG
from utils.as_compat import as_messages, build_chat_model

TOOLS = [{
    "type": "function",
    "function": {
        "name": "hotel_search",
        "description": "搜索某城市的酒店",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]

async def main():
    model = build_chat_model({
        "model_name": LLM_CONFIG["model_name"],
        "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"],
        "generate_kwargs": {"temperature": 0},
    })
    msgs = as_messages([{"role": "user", "content": "帮我查一下杭州的酒店"}])
    try:
        resp = await model(msgs, tools=TOOLS, tool_choice="auto")
        blocks = getattr(resp, "content", []) or []
        kinds = [(getattr(b, "type", "?"), getattr(b, "name", None)) for b in blocks]
        print("OK tool_calling supported; blocks:", kinds)
    except Exception as e:
        print("FAILED:", type(e).__name__, str(e)[:240])

asyncio.run(main())
