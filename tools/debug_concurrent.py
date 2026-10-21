"""并发两条请求（干净用户，无 pending 状态），看会不会互相吞掉。"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:3003"
USER = "concurrent_debug"


def chat(msg: str):
    body = json.dumps({"user_id": USER, "message": msg}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", "replace")
    evs = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            p = line[5:].strip()
            if p and p != "[DONE]":
                try:
                    evs.append(json.loads(p))
                except json.JSONDecodeError:
                    pass
    return {
        "agents": [e.get("agent_name") for e in evs if e.get("type") == "agent_result"],
        "clarify": [e.get("question") for e in evs if e.get("type") == "clarification" or e.get("question")],
        "errors": [e.get("message") for e in evs if e.get("type") == "error"],
    }


msgs = ["上海有什么推荐酒店", "明天上海天气怎么样"]
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(chat, msgs))

for m, r in zip(msgs, results):
    print(f"{m!r}\n   agents={r['agents']} clarify={[c[:30] for c in r['clarify']]} errors={r['errors']}")
