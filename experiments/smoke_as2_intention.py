import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))

from dotenv import load_dotenv
load_dotenv()

from config import LLM_CONFIG
from agents.intention_agent import IntentionAgent
from utils.as_compat import build_chat_model, mk_msg, msg_json, msg_text
import agentscope

async def main():
    print("agentscope:", agentscope.__version__)
    model = build_chat_model({
        "model_name": LLM_CONFIG["model_name"],
        "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"],
        "generate_kwargs": {"temperature": LLM_CONFIG.get("temperature", 0.7)},
    })
    agent = IntentionAgent(name="IntentionRecognitionAgent", model=model)
    x = mk_msg("user", "杭州西湖附近有什么好吃的餐厅", role="user")
    res = await agent.reply(x)
    print("reply type:", type(res).__name__)
    data = msg_json(res, default=None)
    print("parsed intents:", [i.get("type") for i in (data or {}).get("intents", [])])
    print("schedule:", [a.get("agent_name") for a in (data or {}).get("agent_schedule", [])])
    print("rewritten_query:", (data or {}).get("rewritten_query", "")[:60])

asyncio.run(main())
