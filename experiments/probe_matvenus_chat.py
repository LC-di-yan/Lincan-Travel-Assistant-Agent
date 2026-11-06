import asyncio, json, os, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))

BASE = "https://token-api.matvenus.com/v1"
KEY = os.environ.get("PROBE_KEY", "")

# 1) 模型清单里是否有 glm-5.3-flash
req = urllib.request.Request(BASE + "/models", headers={"Authorization": "Bearer " + KEY})
with urllib.request.urlopen(req, timeout=20) as r:
    models = [m["id"] for m in json.loads(r.read())["data"]]
print("model count:", len(models))
print("has glm-5.3-flash:", "glm-5.3-flash" in models)
print("glm-* models:", [m for m in models if m.startswith("glm")][:8])

# 2) 用项目的 build_chat_model 走一次真实调用（验证 2.0.11 模型链路 + 新网关）
from utils.as_compat import as_messages, build_chat_model, msg_text

async def main():
    model = build_chat_model({
        "model_name": "glm-5.3-flash",
        "api_key": KEY,
        "base_url": BASE,
        "generate_kwargs": {"temperature": 0, "max_tokens": 80},
    })
    resp = await model(as_messages([{"role": "user", "content": "只回答两个字：你好"}]))
    print("chat ok, text:", repr(msg_text(resp)[:40]))

asyncio.run(main())
