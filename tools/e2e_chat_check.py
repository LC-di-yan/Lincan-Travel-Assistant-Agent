"""端到端回归：向 /api/chat 发真实用户问题，检查 SSE 事件与最终行程。"""
import json
import sys
import time
import urllib.request

MESSAGE = sys.argv[1] if len(sys.argv) > 1 else "明天从北京去上海出差3天，预算2000"
USER = sys.argv[2] if len(sys.argv) > 2 else "default_user"

body = json.dumps({"user_id": USER, "message": MESSAGE}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:3003/api/chat",
    data=body,
    headers={"Content-Type": "application/json"},
)

t0 = time.time()
events = []
with urllib.request.urlopen(req, timeout=240) as resp:
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("", "[DONE]"):
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        events.append(ev)
        kind = ev.get("type") or ev.get("status") or "?"
        print(f"[{time.time() - t0:5.1f}s] {kind}")

elapsed = time.time() - t0
final = next((e for e in events if e.get("type") == "agent_result"), None)
print(f"\nelapsed={elapsed:.1f}s events={len(events)}")

if not final:
    print("FAIL: 没有 agent_result 事件")
    sys.exit(1)

data = final.get("data") or {}
it = data.get("itinerary") or {}
plans = it.get("daily_plans") or []
acts = sum(len(p.get("activities") or []) for p in plans)
print(f"status={final.get('status')} title={it.get('title')!r} days={len(plans)} activities={acts}")
print(f"planning_complete={data.get('planning_complete')} error={str(data.get('error'))[:60]!r}")
for p in plans[:2]:
    print(f"  D{p.get('day')} {p.get('city')} {p.get('theme')}")
    for a in (p.get("activities") or [])[:2]:
        print(f"    {a.get('time')} {a.get('activity')} @ {str(a.get('location'))[:30]}")

ok = final.get("status") == "success" and plans and acts >= 2 and not data.get("error")
print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 2)
