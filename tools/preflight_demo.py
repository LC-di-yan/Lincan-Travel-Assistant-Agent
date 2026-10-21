"""演示前 3 分钟自检 + 预热。

用法：
    .venv\\Scripts\\python.exe tools\\preflight_demo.py

做四件事：
1. 服务健康检查（/api/health、首页、插件接口）
2. 模型通道探活（verify_llm.py）
3. 预热三条主链路（行程 / 知识库 / 车票），顺便记录耗时
4. 给出「可以开始演示 / 有问题」的结论
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("ALIGO_BASE", "http://127.0.0.1:3003")
WARMUP_USER = "demo_preflight"
RESULTS = []


def check(name: str, path: str, timeout: float = 5.0) -> bool:
    try:
        t0 = time.monotonic()
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            ok = r.status == 200
        cost = (time.monotonic() - t0) * 1000
        RESULTS.append((ok, name, f"{cost:.0f}ms"))
        return ok
    except Exception as e:  # noqa: BLE001
        RESULTS.append((False, name, str(e)[:60]))
        return False


def chat(message: str, timeout: float = 180.0):
    """发一条消息，返回 (耗时, 命中的 agents, 首句摘要, 是否成功)。"""
    body = json.dumps({"user_id": WARMUP_USER, "message": message}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        BASE + "/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return time.monotonic() - t0, [], f"请求失败: {e}", False
    cost = time.monotonic() - t0

    agents, text, ok = [], "", False
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
        if ev.get("type") == "agent_result":
            agents.append(ev.get("agent_name") or "")
            ok = ok or ev.get("status") == "success"
            d = ev.get("data") or {}
            text = (
                (d.get("results") or {}).get("summary")
                or d.get("answer")
                or d.get("proactive_question")
                or text
            )
        elif ev.get("type") == "error":
            text = "ERROR: " + str(ev.get("message"))[:60]
    return cost, agents, (text or "")[:80].replace("\n", " "), ok


def main() -> int:
    print("=" * 62)
    print("  Aligo 演示自检")
    print("=" * 62)

    if not check("服务健康 /api/health", "/api/health"):
        print("\n[×] 服务没起来。先执行：  .\\start-demo.ps1")
        return 1
    check("首页 HTML", "/")
    check("插件接口 /api/plugins", "/api/plugins")

    print("\n── 模型通道 ─────────────────────────────────────")
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        out = subprocess.run(
            [sys.executable, "verify_llm.py"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=env,
        )
        output = out.stdout or out.stderr or ""
        tail = [ln for ln in output.splitlines() if "结论" in ln or "OK" in ln or "FAIL" in ln]
        print("\n".join(tail[-4:]) or output[-300:])
        channel_ok = ("模型通道可用" in output) or ("[OK" in output)
        RESULTS.append((channel_ok, "模型通道探活", "可用" if channel_ok else "见上方输出"))
    except Exception as e:  # noqa: BLE001
        print(f"verify_llm 执行失败: {e}")
        RESULTS.append((False, "模型通道探活", str(e)[:60]))

    print("\n── 预热主链路 ───────────────────────────────────")
    warmups = [
        ("行程规划", "明天从北京去上海出差3天，预算2000"),
        ("知识库（含依据）", "上海住宿标准是多少"),
        ("车票查询", "看看明早从北京去上海的高铁票有哪些"),
    ]
    for label, msg in warmups:
        cost, agents, text, ok = chat(msg)
        flag = "OK " if ok else "!! "
        print(f"{flag}{label:<10} {cost:5.1f}s  {agents}")
        print(f"   {text}")
        RESULTS.append((ok, f"预热·{label}", f"{cost:.1f}s"))

    tts = os.environ.get("MIMO_API_KEY", "").strip()
    if not tts:
        print("\n[!] 未配置 MIMO_API_KEY：朗读按钮不可用，演示时不要点。")

    print("\n── 结论 ─────────────────────────────────────────")
    failed = [r for r in RESULTS if not r[0]]
    if failed:
        print(f"[×] {len(failed)} 项未通过：")
        for _, name, detail in failed:
            print(f"    - {name}: {detail}")
        print("\n排查：.\\stop-demo.ps1 后重新 .\\start-demo.ps1；仍失败看 logs\\server.log")
        return 1

    print("[√] 全部通过，可以开始演示。建议再手动点一次「新对话」。")
    print("    演示脚本见 docs/DEMO_SCRIPT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
