import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
from config import LLM_CONFIG
from agents.intention_agent import IntentionAgent
from utils.as_compat import build_chat_model, mk_msg, msg_json

async def main():
    model = build_chat_model({
        "model_name": LLM_CONFIG["model_name"], "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"], "generate_kwargs": {"temperature": 0},
    })
    agent = IntentionAgent(name="WeatherGuardCheck", model=model)
    for q in ["今天天气真不错啊", "杭州下周天气怎么样"]:
        res = await agent.reply(mk_msg("user", q, role="user"))
        d = msg_json(res, default={}) or {}
        intents = [x.get("type") for x in d.get("intents", [])]
        agents = [a.get("agent_name") for a in d.get("agent_schedule", [])]
        print(f"RESULT {q} -> intents={intents} agents={agents}", flush=True)

asyncio.run(main())