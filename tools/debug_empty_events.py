"""看这几类输入到底返回了什么事件（为什么没有 agent_result）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:3003"


def chat(msg: str, user: str = "edge_debug"):
    body = json.dumps({"user_id": user, "message": msg}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", "replace")
    print(f"\n=== {msg[:40]!r} ===")
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if not p or p == "[DONE]":
            continue
        try:
            ev = json.loads(p)
        except json.JSONDecodeError:
            continue
        print(" -", json.dumps(ev, ensure_ascii=False)[:260])


chat("")
chat("   ")
chat("明天去上海🚄出差3天，预算💰2000")
chat("上海有什么推荐酒店")
