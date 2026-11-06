import asyncio, inspect, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
from agentscope.classifier import JevClassifierModel
from agentscope.credential import TypeSafeCredential

key = os.environ["NEOHOUSE_API_KEY"]
m = JevClassifierModel(credential=TypeSafeCredential(api_key=key, base_url="https://tokenrhythm.studio"),
                       model="NeoHorse-Jev-4B", timeout=15)
print("client type:", type(m.client).__name__)
print("has compression attr:", hasattr(m.client, "compression"))
print("compression value:", getattr(m.client, "compression", "N/A"))
sig = inspect.signature(type(m.client).__init__)
print("client init default compression:", sig.parameters.get("compression").default)

# 关闭压缩后跑一个大 body（13 类 criteria + 6 门控）
from utils.decision_jev import translate_questions
from utils.decision_schema import build_questions
qs = build_questions()
big_state = "用户问：帮我安排杭州出差一周的行程，住在西湖附近，想吃本地菜，预算有限。历史记录：上一轮问了酒店。" * 6

async def main():
    m.client.compression = False
    wire = None
    resp = await m(big_state, translate_questions(qs))
    print("OK answers:", {k: getattr(a, "type", None) for k, a in resp.content.items()})

asyncio.run(main())
