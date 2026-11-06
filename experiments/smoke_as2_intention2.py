import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))

from dotenv import load_dotenv
load_dotenv()

from config import LLM_CONFIG
from agents.intention_agent import IntentionAgent
from utils.as_compat import build_chat_model, mk_msg, msg_json
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
    x = mk_msg("user", "明年三月带老人家去京都看樱花，腿脚不便需要轮椅友好、含早餐的酒店，行程别太赶", role="user")
    res = await agent.reply(x)
    data = msg_json(res, default=None)
    if data is None:
        print("PARSE FAILED, raw text head:", msg_text(res)[:200])
        return
    print("parsed intents:", [i.get("type") for i in data.get("intents", [])])
    print("schedule:", [a.get("agent_name") for a in data.get("agent_schedule", [])])
    print("needs_clarification:", data.get("needs_clarification"))

asyncio.run(main())
