"""通道体检：给一个 base_url + key，逐个模型发 1 token 的 ping，打印状态码。

用途：换 key / 换服务商时，30 秒判断「这把 key 到底能不能用、卡在哪」。
不读 .env，不打印完整 key（只显示首尾）。

用法：
    python tools/probe_key.py https://xxx/v1 sk-xxxx deepseek-v4.1-flash-1017
    python tools/probe_key.py https://xxx/v1 sk-xxxx model-a,model-b

常见状态码：
    200 = 可用
    401 = key 无效 / 过期
    403 AccessDenied.Unpurchased = 该 workspace 没有这个模型的授权或额度
    404 Model not exist         = 模型名不对（能走到这步说明鉴权已通过）
    429 = 限流
"""
import json
import sys
import time
import urllib.error
import urllib.request


def mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else "***"


def ping(base: str, key: str, model: str) -> tuple[int, str, float]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as exc:  # noqa: BLE001
        return -1, f"EXC {exc}", time.time() - t0


def classify(code: int, text: str) -> str:
    low = text.lower()
    if code == 200:
        return "可用"
    if "arrearage" in low or "overdue" in low or "not in good standing" in low:
        return "账号欠费（Arrearage）——结清欠费即恢复"
    if "unpurchased" in low:
        return "该模型未购买/未开通"
    if "workspace endpoint" in low:
        return "这把 key 不属于该 workspace 专属入口"
    if code == 401:
        return "Key 无效或已过期"
    if code == 404:
        return "模型名不存在（鉴权已通过）"
    if code == 429:
        return "限流"
    return "见原始返回"


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    base, key, models = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
    print(f"base_url : {base}")
    print(f"api_key  : {mask(key)}\n")

    ok = 0
    for model in models:
        code, text, dt = ping(base, key, model)
        reason = classify(code, text)
        if code == 200:
            ok += 1
        print(f"{model:<34} {code:>4}  {dt:5.1f}s  {reason}")
        if code != 200:
            snippet = " ".join(text.split())[:180]
            print(f"{'':<34}        {snippet}")

    print(f"\n结论：{ok}/{len(models)} 个模型可用")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
