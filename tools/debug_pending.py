"""复现：先触发「缺出发地」追问，紧接着问酒店，看会不会被当成答案吞掉。"""
import json
import urllib.request

BASE = "http://127.0.0.1:3003"
USER = "pending_debug"


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
    summary = []
    for e in evs:
        if e.get("type") == "agent_result":
            summary.append("agent=" + str(e.get("agent_name")))
        elif e.get("type") == "clarification" or e.get("question"):
            summary.append("clarify=" + str(e.get("question"))[:40])
        elif "reasoning" in e:
            summary.append("reasoning=" + str(e.get("reasoning"))[:50])
    print(f"\n>>> {msg!r}")
    for s in summary:
        print("   ", s)


chat("明天去上海出差3天，预算2000")
chat("上海有什么推荐酒店")
chat("那从北京出发呢")
