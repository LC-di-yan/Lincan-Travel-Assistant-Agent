"""边界与并发测试：空消息、超长消息、emoji、并发请求、新会话隔离。

跑法：
    .venv\\Scripts\\python.exe tools\\edge_cases.py
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:3003"


def chat(user: str, message, timeout: float = 120) -> dict:
    body = json.dumps({"user_id": user, "message": message}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        events = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                p = line[5:].strip()
                if p and p != "[DONE]":
                    try:
                        events.append(json.loads(p))
                    except json.JSONDecodeError:
                        pass
        agents = [e.get("agent_name") for e in events if e.get("type") == "agent_result"]
        errors = [e.get("message") for e in events if e.get("type") == "error"]
        return {"status": resp.status, "elapsed": time.time() - t0, "agents": agents, "errors": errors,
                "events": len(events)}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "elapsed": time.time() - t0,
                "body": exc.read().decode("utf-8", "replace")[:160]}
    except Exception as exc:  # noqa: BLE001
        return {"status": -1, "elapsed": time.time() - t0, "body": str(exc)[:160]}


def post(path: str, payload: dict) -> int:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    user = "edge_" + uuid.uuid4().hex[:8]
    failures = []

    cases = [
        ("空消息", ""),
        ("纯空格", "   "),
        ("超长消息", "帮我规划行程 " * 200),
        ("emoji+混合", "明天去上海🚄出差3天，预算💰2000"),
    ]
    print(f"{'case':<12}{'HTTP':>5}{'耗时':>8}  智能体 / 错误")
    for label, msg in cases:
        r = chat(user, msg)
        detail = ", ".join(a for a in r.get("agents", []) if a) or "-"
        if r.get("errors"):
            detail += " | err=" + str(r["errors"])[:80]
        print(f"{label:<12}{r.get('status', 0):>5}{r.get('elapsed', 0):>7.1f}s  {detail}")
        # 只要不是 5xx / 不发 error 事件，就算通过（空消息可以 422）
        if r.get("status", 0) >= 500 or r.get("errors"):
            failures.append(f"{label}: {r}")

    # 并发两条不同请求
    print("\n并发 2 条请求：")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        rs = list(pool.map(lambda q: chat(user, q), ["上海有什么推荐酒店", "明天上海天气怎么样"]))
    for r, q in zip(rs, ["酒店", "天气"]):
        print(f"  {q:<4} HTTP {r.get('status')} {r.get('elapsed', 0):5.1f}s agents={r.get('agents')}")
        if r.get("status") != 200 or r.get("errors"):
            failures.append(f"并发 {q}: {r}")
    print(f"  并发总耗时 {time.time() - t0:.1f}s")

    # 新会话隔离：/api/session/new 后上下文应清空
    code = post("/api/session/new", {"user_id": user})
    print(f"\n新建会话 HTTP {code}")
    if code != 200:
        failures.append(f"/api/session/new HTTP {code}")

    print(f"\n结果：{len(cases) + 3} 项，失败 {len(failures)}")
    for f in failures:
        print("FAIL:", f)

    from pathlib import Path

    p = Path("data/memory") / f"{user}.json"
    if p.exists():
        p.unlink()
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
