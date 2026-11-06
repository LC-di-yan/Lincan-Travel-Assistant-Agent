import asyncio, importlib.util, json, sys, time
from pathlib import Path
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from config_agentscope import init_agentscope
init_agentscope()
from config import LLM_CONFIG
from agentscope.model import OpenAIChatModel

model = OpenAIChatModel(
    model_name=LLM_CONFIG["model_name"],
    api_key=LLM_CONFIG["api_key"],
    stream=False,
    client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
    generate_kwargs={"temperature": 0.3, "max_tokens": 2048},
)

spec = importlib.util.spec_from_file_location("rag", ROOT/".claude/skills/ask-question/script/agent.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
agent = mod.RAGKnowledgeAgent(name="RAG", model=model)

def content_of(msg):
    c = msg.content
    if isinstance(c, str): return c
    return "\n".join(b.get("text","") if isinstance(b,dict) else getattr(b,"text","") for b in c)

QUERIES = [
    "北京出差的住宿标准是多少？",
    "杭州住宿费上限是多少？",
    "发票抬头要开成什么？",
    "航班延误了怎么办？",
    "出差可以带家属吗？",
]
async def main():
    for q in QUERIES:
        t0 = time.time()
        msg = await agent.reply(type("M",(),{"content":q})())
        dt = time.time() - t0
        data = json.loads(content_of(msg))
        print(f"\nQ: {q}  ({dt:.1f}s)")
        print("  status:", data.get("status"), "| number_check:", data.get("number_check"), "| retrieval:", data.get("retrieval"))
        print("  sources:", [(s.get("path"), s.get("lines")) for s in data.get("sources", [])][:3])
        print("  answer :", (data.get("answer") or "")[:160].replace("\n", " / "))
asyncio.run(main())
