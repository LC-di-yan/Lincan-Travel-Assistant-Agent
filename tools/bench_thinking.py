"""验证上游是否支持 enable_thinking=False（关掉思考以提速），并对比耗时。

key 从 .env / 环境变量读，不写死在代码里。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

BASE = os.environ.get("ALIGO_BASE_URL", "").rstrip("/")
KEY = os.environ.get("ALIGO_API_KEY", "")
if not BASE or not KEY:
    raise SystemExit("缺少 ALIGO_BASE_URL / ALIGO_API_KEY：请在 .env 里配置")

PROMPT = (
    "只输出JSON，不要解释："
    '{"itinerary":{"title":"","duration":"","daily_plans":[{"day":1,"city":"","theme":"",'
    '"activities":[{"time":"","activity":"","location":"","description":""}]}]}}\n'
    "为「北京到上海出差3天」排 3 天，每天 2-3 个活动。"
)


def call(model: str, thinking: bool | None, max_tokens: int = 2000) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    if thinking is not None:
        payload["enable_thinking"] = thinking
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
        dt = time.time() - t0
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        content = msg.get("content") or ""
        ok = content.strip().startswith("{") or "```" in content or "{" in content
        return {"ok": ok, "dt": dt, "rc": len(msg.get("reasoning_content") or ""), "chars": len(content),
                "head": " ".join(content.split())[:70]}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "dt": time.time() - t0, "err": f"HTTP {exc.code} " + exc.read().decode("utf-8", "replace")[:140]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "dt": time.time() - t0, "err": str(exc)[:140]}


for model in sys.argv[1].split(","):
    for thinking in (None, False):
        r = call(model, thinking)
        label = "default" if thinking is None else "thinking=False"
        if r["ok"]:
            print(f"{model:<28}{label:<16}{r['dt']:6.1f}s  reasoning={r['rc']:>5}字  content={r['chars']:>5}字  {r['head']}")
        else:
            print(f"{model:<28}{label:<16}{r['dt']:6.1f}s  FAILED {r['err']}")
