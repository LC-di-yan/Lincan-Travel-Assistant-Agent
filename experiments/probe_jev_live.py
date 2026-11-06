import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
import os
from utils.decision_jev import JevDecisionBackend

async def main():
    be = JevDecisionBackend(
        api_key=os.environ["NEOHOUSE_API_KEY"],
        base_url=os.environ.get("NEOHOUSE_BASE_URL", "https://tokenrhythm.studio/v1"),
        model=os.environ.get("NEOHOUSE_MODEL", "NeoHorse-Jev-4B"),
        timeout=15,
    )
    qs = {"is_request": {"type": "noul", "instructions": "这一句是查询请求吗？"}, 
          "intent": {"type": "choice", "instructions": "主要意图", "criteria": {"hotel_search": "找酒店", "chitchat": "闲聊"}}}
    try:
        wire = await be.decide("帮我订杭州西湖边的酒店", qs)
        import json
        print("OK:", json.dumps(wire, ensure_ascii=False)[:300])
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:300])

asyncio.run(main())
