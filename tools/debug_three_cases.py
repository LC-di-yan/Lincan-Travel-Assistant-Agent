"""复现全量测试里 3 个可疑点：单日行程无结果、偏好/费用未落盘。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:3003"
USER = "debug_cases"


def chat(msg: str, timeout: float = 120):
    body = json.dumps({"user_id": USER, "message": msg}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("data:"):
                p = text[5:].strip()
                if p and p != "[DONE]":
                    try:
                        events.append(json.loads(p))
                    except json.JSONDecodeError:
                        pass
    print(f"\n=== {msg}  ({time.time() - t0:.1f}s, {len(events)} events) ===")
    for ev in events:
        keys = [k for k in ev.keys()]
        print(" -", json.dumps(ev, ensure_ascii=False)[:300])
    return events


def get(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


chat("上海一日游怎么安排")
chat("我住酒店喜欢全季")
chat("今天打车花了80元")

print("\n=== /api/preferences ===")
print(get(f"/api/preferences?user_id={USER}")[:600])
print("\n=== /api/expenses ===")
print(get(f"/api/expenses?user_id={USER}")[:600])

import io
p = f"data/memory/{USER}.json"
print(f"\n=== {p} ===")
try:
    d = json.load(io.open(p, encoding="utf-8"))
    print("keys:", list(d))
    print("preferences:", json.dumps(d.get("preferences"), ensure_ascii=False)[:300])
    print("expenses:", json.dumps(d.get("expenses"), ensure_ascii=False)[:300])
    print("trips:", len(d.get("trip_history") or []))
except FileNotFoundError:
    print("文件不存在")
