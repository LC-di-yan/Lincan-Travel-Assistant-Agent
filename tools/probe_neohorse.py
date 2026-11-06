"""TokenRhythm 决策模型体检：确认 NeoHorse-Jev-4B 是否可用、接口长什么样。

用途：接入前 30 秒判断「这把 key 能不能用、模型怎么调」。
不读 .env，不打印完整 key（只显示首尾）。

用法：
    $env:TR_KEY="sk-xxx"; python tools/probe_neohorse.py
    python tools/probe_neohorse.py --base https://tokenrhythm.studio/v1 --key sk-xxx

探测内容：
    1. GET  /models                       —— 模型清单与能力位
    2. POST /chat/completions  messages   —— 普通聊天调用是否被接受
    3. POST /chat/completions  questions  —— 结构化决策字段是否被接受
    4. GET  /openapi.json  /docs          —— 是否有独立决策端点
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = os.environ.get("TR_BASE_URL", "https://tokenrhythm.studio/v1")
CANDIDATE = "NeoHorse-Jev-4B"


def mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else "***"


def call(method: str, url: str, key: str, payload: dict | None = None) -> tuple[int, str, float]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method=method,
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as exc:  # noqa: BLE001
        return -1, f"EXC {exc}", time.time() - t0


def brief(text: str, n: int = 400) -> str:
    return " ".join(text.split())[:n]


def main() -> int:
    argv = sys.argv[1:]
    base = DEFAULT_BASE
    key = os.environ.get("TR_KEY", "")
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
    if "--key" in argv:
        key = argv[argv.index("--key") + 1]
    if not key:
        print(__doc__)
        print("缺少 key：设置 $env:TR_KEY 或传 --key")
        return 2

    print(f"base_url : {base}")
    print(f"api_key  : {mask(key)}\n")

    # 1. 模型清单
    code, text, dt = call("GET", f"{base.rstrip('/')}/models", key)
    print(f"[1] GET /models              {code:>4}  {dt:5.1f}s")
    ids: list[str] = []
    hits: list[dict] = []
    if code == 200:
        try:
            data = json.loads(text)
            models = data.get("data") or []
            ids = [m.get("id", "") for m in models]
            hits = [m for m in models if any(k in m.get("id", "").lower() for k in ("horse", "jev"))]
            print(f"    共 {len(ids)} 个模型")
            print(f"    命中 horse/jev: {[m.get('id') for m in hits]}")
            for m in hits:
                print("    " + json.dumps({
                    k: m.get(k) for k in (
                        "id", "context_length", "max_completion_tokens",
                        "supports_tools", "supports_reasoning", "supports_vision",
                        "effective_input_price_per_million", "effective_output_price_per_million",
                    )
                }, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(f"    解析失败: {exc}")
    else:
        print("    " + brief(text))

    model = hits[0]["id"] if hits else CANDIDATE
    print(f"\n    使用模型: {model}")

    # 2. 普通聊天调用
    code, text, dt = call("POST", f"{base.rstrip('/')}/chat/completions", key, {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    })
    print(f"\n[2] POST /chat/completions (messages)  {code:>4}  {dt:5.1f}s")
    print("    " + brief(text, 600))

    # 3. 结构化决策字段
    code, text, dt = call("POST", f"{base.rstrip('/')}/chat/completions", key, {
        "model": model,
        "state": "明天从北京去上海出差3天",
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "用户想做什么？",
                "criteria": {
                    "itinerary_planning": "规划行程/出差安排",
                    "information_query": "查询天气等实时信息",
                    "expense_tracking": "记账报销",
                    "chitchat": "闲聊",
                },
            },
            "need_clarify": {"type": "noul", "instructions": "是否缺少出发地或目的地？"},
        },
    })
    print(f"\n[3] POST /chat/completions (state+questions)  {code:>4}  {dt:5.1f}s")
    print("    " + brief(text, 800))

    # 4. 文档/决策端点
    for path in ("/openapi.json", "/docs"):
        code, text, dt = call("GET", base.rstrip("/") + path, key)
        print(f"\n[4] GET {path:<12}         {code:>4}  {dt:5.1f}s  {brief(text, 160) if code != 200 else 'OK'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
