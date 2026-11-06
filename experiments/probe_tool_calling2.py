import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
from config import LLM_CONFIG
from utils.as_compat import as_messages, build_chat_model
from agentscope.tool import ToolChoice

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
    for mode in ["auto", "required", "hotel_search"]:
        try:
            tc = ToolChoice(mode=mode)
            resp = await model(msgs, tools=TOOLS, tool_choice=tc)
            blocks = [(getattr(b, "type", "?"), getattr(b, "name", None)) for b in (getattr(resp, "content", []) or [])]
            print(f"[{mode}] OK blocks={blocks}")
        except Exception as e:
            print(f"[{mode}] FAILED: {type(e).__name__}: {str(e)[:180]}")

asyncio.run(main())
