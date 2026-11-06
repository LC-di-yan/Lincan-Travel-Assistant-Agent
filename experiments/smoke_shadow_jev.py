import asyncio, glob, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
from utils.decision_router import maybe_use_decision

async def main():
    hook = await maybe_use_decision("帮我订杭州西湖边的酒店", history=[])
    print("source:", hook.source, "| trace:", hook.trace_id, "| engine backend:", getattr(hook.engine, "backend", None))
    await asyncio.sleep(4)
    logs = sorted(glob.glob("data/decision_shadow/*.jsonl"))
    print("shadow log files:", [os.path.basename(x) for x in logs][-2:])
    if logs:
        with open(logs[-1], encoding="utf-8") as f:
            recs = [json.loads(l) for l in f.read().strip().splitlines() if l.startswith("{")]
        last = recs[-1]
        print("record keys:", sorted(last.keys()))
        print("intent:", (last.get("decision") or {}).get("intent"),
              "| latency_ms:", (last.get("decision") or {}).get("latency_ms"))

asyncio.run(main())
