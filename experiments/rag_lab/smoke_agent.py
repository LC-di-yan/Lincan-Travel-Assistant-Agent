import asyncio, importlib.util, json, sys
from pathlib import Path

def content_of(msg):
    c = msg.content
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "") for b in c)
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("rag_agent_test", ROOT/".claude/skills/ask-question/script/agent.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

async def t1():
    agent = mod.RAGKnowledgeAgent(name="RAG", model=None)
    msg = await agent.reply(type("M",(),{"content":"北京出差的住宿标准是多少？"})())
    data = json.loads(content_of(msg))
    print("T1 status:", data["status"])
    print("T1 sources:", [(s["file"], s["path"], s["lines"]) for s in data["sources"]])
    print("T1 answer:", data["answer"][:120])
    print("T1 retrieval:", data.get("retrieval"))

class StubModel:
    async def __call__(self, messages):
        text = messages[-1]["content"]
        if "候选节点" in text:
            if "一线城市住宿标准" not in text and "三、住宿标准" in text:
                return type("R",(),{"content":json.dumps({"selected":["01#h1-3"],"expand":True,"confidence":0.9})})()
            return type("R",(),{"content":json.dumps({"selected":["01#h1-3#h2-1"],"expand":False,"confidence":0.9})})()
        if "文档列表" in text:
            return type("R",(),{"content":json.dumps({"doc_ids":["01_travel_standards"],"confidence":0.9})})()
        if "知识原文" in text:
            return type("R",(),{"content":json.dumps({"answer":"一线城市（北京、上海、广州、深圳）住宿标准为不超过600元/晚。","proactive_question":"需要我帮你查二线标准吗？"})})()
        return type("R",(),{"content":"{}"})()

async def t2():
    agent = mod.RAGKnowledgeAgent(name="RAG", model=StubModel())
    msg = await agent.reply(type("M",(),{"content":"上海住宿标准多少"})())
    data = json.loads(content_of(msg))
    print("T2 answer:", data["answer"][:80])
    print("T2 number_check:", data["number_check"], "| proactive:", data["proactive_question"])
    print("T2 sources:", [(s["path"], s["lines"]) for s in data["sources"]])

async def main():
    await t1()
    print("-"*60)
    await t2()
asyncio.run(main())