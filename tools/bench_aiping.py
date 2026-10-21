"""在 aiping 上给候选模型跑同一道「行程 JSON」题，比较耗时/格式/内容。

题目尽量贴近 plan-trip 的真实 prompt（中文、要求严格 JSON、3 天 9 个活动）。

key 从 .env / 环境变量读，不写死在代码里：
    ALIGO_BASE_URL / ALIGO_API_KEY
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

BASE = os.environ.get("ALIGO_BASE_URL", "https://aiping.cn/api/v1").rstrip("/")
KEY = os.environ.get("ALIGO_API_KEY", "")
if not KEY:
    raise SystemExit("缺少 ALIGO_API_KEY：请在 .env 里配置，或先 export 一个可用 key")

PROMPT = """你是行程规划专家。根据以下信息生成行程。

【当前时间】2026年10月20日 星期二
【需求】明天从北京去上海出差3天，预算2000
【用户偏好】酒店偏好: 汉庭
【信息】
{"user_query": "明天从北京去上海出差3天，预算2000", "event_collection": {"origin": "北京", "destination": "上海", "duration_days": 3, "trip_purpose": "出差"}}

【输出要求】（严格遵守）
1. 每日最多3个活动，每个描述不超过80字
2. 总行程不超过5天
3. 所有字符串值必须用英文双引号包围，内部引号用 \\" 转义
4. 不要在字符串值中使用换行符
5. 确保JSON格式完整，可直接被解析

直接输出JSON：
{"itinerary": {"title": "", "duration": "", "route": "", "daily_plans": [{"day": 1, "date": "", "city": "", "theme": "", "activities": [{"time": "", "activity": "", "location": "", "description": ""}], "meals": {"breakfast": "", "lunch": "", "dinner": ""}}]}, "budget": {"total": "", "breakdown": []}, "proactive_question": ""}"""


def call(model: str, max_tokens: int = 3000) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.load(resp)
        dt = time.time() - t0
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return {
            "ok": True,
            "dt": dt,
            "content": msg.get("content") or "",
            "reasoning_chars": len(msg.get("reasoning_content") or ""),
            "usage": data.get("usage") or {},
            "finish": choice.get("finish_reason"),
        }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "dt": time.time() - t0, "err": f"HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:160]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "dt": time.time() - t0, "err": str(exc)[:160]}


def score(content: str) -> tuple[bool, int, int, str]:
    """返回 (能否解析, 天数, 活动数, 备注)"""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    if start < 0:
        return False, 0, 0, "no json object"
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except Exception as exc:  # noqa: BLE001
        return False, 0, 0, f"parse error: {exc}"
    it = obj.get("itinerary") or {}
    plans = it.get("daily_plans") or []
    acts = sum(len(p.get("activities") or []) for p in plans)
    return True, len(plans), acts, (it.get("title") or "")[:24]


def main() -> int:
    models = sys.argv[1].split(",")
    print(f"{'model':<28}{'耗时':>7}{'推理字':>7}{'解析':>6}{'天':>4}{'活动':>5}  标题")
    for m in models:
        r = call(m)
        if not r["ok"]:
            print(f"{m:<28}{r['dt']:>6.1f}s  FAILED  {r['err']}")
            continue
        ok, days, acts, note = score(r["content"])
        print(f"{m:<28}{r['dt']:>6.1f}s{r['reasoning_chars']:>7}{'OK' if ok else 'FAIL':>6}{days:>4}{acts:>5}  {note}")
        if not ok:
            print(f"{'':<28}raw: {r['content'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
