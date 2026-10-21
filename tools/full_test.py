"""全量端到端测试：把 9 大意图 + 记忆/偏好/费用 + REST 接口 + 前端资源全跑一遍。

用法：
    .venv\\Scripts\\python.exe tools\\full_test.py
    .venv\\Scripts\\python.exe tools\\full_test.py --base http://127.0.0.1:3003 --keep

判定：
    - 不能出现 error 事件
    - 响应里不能出现上游报错（AccessDenied / Error code: / sk-ws-）
    - 必须至少有一个 agent_result
    - 期望的智能体出现在实际执行列表里（只告警，不硬判失败，便于发现路由漂移）
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

LEAK_MARKERS = ("AccessDenied", "Error code:", "sk-ws-", "Traceback", "Unpurchased")

# (id, 话术, 期望智能体, 说明)
CASES = [
    ("itinerary_3d", "明天从北京去上海出差3天，预算2000", {"itinerary_planning"}, "行程规划·多日"),
    ("itinerary_1d", "上海一日游怎么安排", {"itinerary_planning"}, "行程规划·单日"),
    ("hotel", "上海有什么推荐酒店", {"hotel_search"}, "酒店搜索"),
    ("restaurant", "上海有什么好吃的", {"restaurant_search"}, "餐厅搜索"),
    ("scenic", "上海有什么好玩的地方", {"scenic_search"}, "景点搜索"),
    ("weather", "明天上海天气怎么样", {"information_query"}, "天气查询"),
    ("train", "查一下明天北京到上海的高铁", {"train_ticket"}, "火车票"),
    ("pref_write", "我住酒店喜欢全季", {"preference"}, "偏好写入"),
    ("pref_read", "我有什么偏好", {"memory_query"}, "偏好查询（走记忆）"),
    ("expense", "今天打车花了80元", {"expense_tracking"}, "费用记录"),
    ("currency", "100美元等于多少人民币", {"currency_conversion"}, "汇率换算"),
    ("translate", "把「你好」翻译成英文", {"translation"}, "翻译"),
    ("rag", "出差住宿报销标准是多少", {"rag_knowledge"}, "知识库问答"),
    ("memory", "我之前说过什么", {"memory_query"}, "记忆查询"),
    ("context_followup", "那住哪儿方便", {"hotel_search"}, "多轮追问（依赖上文）"),
    ("clarify", "帮我订个酒店", set(), "缺参数应追问"),
]


def post_json(base: str, path: str, payload: dict, timeout: float = 30) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def get_json(base: str, path: str, timeout: float = 15) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def chat(base: str, user: str, message: str, timeout: float = 180) -> dict:
    body = json.dumps({"user_id": user, "message": message}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    events, raw = [], []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for line in resp:
                text = line.decode("utf-8", "replace").strip()
                if not text.startswith("data:"):
                    continue
                payload = text[5:].strip()
                if payload in ("", "[DONE]"):
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "elapsed": time.time() - t0, "error": str(exc), "events": events}

    raw = json.dumps(events, ensure_ascii=False)
    agents, statuses, errors, clarifications = [], [], [], []
    for ev in events:
        if ev.get("type") == "agent_result":
            agents.append(ev.get("agent_name"))
            statuses.append(ev.get("status"))
        if ev.get("type") == "error":
            errors.append(str(ev.get("message")))
        if ev.get("type") == "clarification" or ev.get("needs_clarification"):
            q = ev.get("question") or ev.get("clarification_question") or ev.get("message") or ""
            if q:
                clarifications.append(str(q)[:60])

    leaks = [m for m in LEAK_MARKERS if m in raw]
    ok = bool(agents) or bool(clarifications)
    return {
        "ok": ok and not errors and not leaks,
        "elapsed": time.time() - t0,
        "events": len(events),
        "agents": agents,
        "statuses": statuses,
        "errors": errors,
        "clarifications": clarifications,
        "leaks": leaks,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3003")
    ap.add_argument("--keep", action="store_true", help="保留测试用户的记忆文件")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    user = "fulltest_" + uuid.uuid4().hex[:8]

    print(f"目标服务 : {base}")
    print(f"测试用户 : {user}\n")

    failures = []
    warnings = []

    # ── 0. 健康 / 前端 ────────────────────────────────────────
    print("── 基础设施 " + "─" * 44)
    for label, path, expect in [
        ("健康检查", "/api/health", 200),
        ("首页 HTML", "/", 200),
        ("偏好接口", f"/api/preferences?user_id={user}", 200),
        ("费用接口", f"/api/expenses?user_id={user}", 200),
        ("插件接口", "/api/plugins", 200),
        ("语音角色", "/api/tts/personas", 200),
    ]:
        code, body = get_json(base, path)
        ok = code == expect
        print(f"{'PASS' if ok else 'FAIL'}  {label:<8} {path:<38} HTTP {code}")
        if not ok:
            failures.append(f"{label} -> HTTP {code} {body[:100]}")

    # 前端 JS 资源
    code, html = get_json(base, "/")
    asset = ""
    if 'src="/assets/' in html:
        asset = html.split('src="/assets/', 1)[1].split('"', 1)[0]
        acode, _ = get_json(base, "/assets/" + asset)
        ok = acode == 200
        print(f"{'PASS' if ok else 'FAIL'}  {'前端 JS':<8} /assets/{asset[:28]}…  HTTP {acode}")
        if not ok:
            failures.append(f"前端 JS HTTP {acode}")

    # ── 1. 九大意图 ──────────────────────────────────────────
    print("\n── 意图矩阵 " + "─" * 44)
    print(f"{'case':<14}{'耗时':>7}{'事件':>5}  实际智能体 / 结果")
    for cid, msg, expect, desc in CASES:
        r = chat(base, user, msg)
        got = set(a for a in r.get("agents", []) if a)
        missed = expect - got
        ok = r["ok"] and not missed
        if r["ok"] and missed:
            # 路由命中别的智能体：只告警，便于发现「已读乱回」式漂移
            warnings.append(f"{cid}: 期望 {sorted(expect)} 实际 {sorted(got)}")
            ok = True
        if not got and r.get("clarifications"):
            head = f"追问: {r['clarifications'][0]}"
        else:
            head = ", ".join(sorted(got)) or "-"
        detail = ""
        if r.get("errors"):
            detail = " | errors=" + " / ".join(r["errors"])[:120]
        if r.get("leaks"):
            detail += " | LEAK=" + ",".join(r["leaks"])
        print(f"{cid:<14}{r.get('elapsed', 0):>6.1f}s{r.get('events', 0):>5}  {head}{detail}")
        if not ok:
            failures.append(f"{cid} ({desc}): {detail or r.get('error', '')[:120]}")

    # ── 2. 记忆落盘 ──────────────────────────────────────────
    print("\n── 记忆/偏好落盘 " + "─" * 38)
    code, body = get_json(base, f"/api/preferences?user_id={user}")
    has_pref = "全季" in body
    print(f"{'PASS' if has_pref else 'FAIL'}  偏好已写入     全季 在 /api/preferences 中")
    if not has_pref:
        failures.append("偏好「全季」没有落到 /api/preferences")

    code, body = get_json(base, f"/api/expenses?user_id={user}")
    has_expense = "80" in body
    print(f"{'PASS' if has_expense else 'WARN'}  费用已记录     80 元 在 /api/expenses 中")
    if not has_expense:
        warnings.append("费用 80 元未在 /api/expenses 中检索到")

    code, body = get_json(base, f"/api/context?user_id={user}")
    print(f"{'PASS' if code == 200 else 'FAIL'}  上下文接口     HTTP {code}  {len(body)} 字节")
    if code != 200:
        failures.append(f"/api/context HTTP {code}")

    # ── 3. 结果 ─────────────────────────────────────────────
    print("\n── 汇总 " + "─" * 48)
    print(f"用例 {len(CASES)} 个，失败 {len(failures)}，警告 {len(warnings)}")
    for w in warnings:
        print("WARN:", w)
    for f in failures:
        print("FAIL:", f)

    if not args.keep:
        from pathlib import Path

        p = Path("data/memory") / f"{user}.json"
        if p.exists():
            p.unlink()
            print(f"已清理测试用户记忆：{p.name}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
