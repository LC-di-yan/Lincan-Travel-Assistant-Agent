import asyncio, importlib.util, json, sys
from pathlib import Path
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("visa_agent_test", ROOT/".claude/skills/visa-info/script/agent.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def content_of(msg):
    c = msg.content
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "") for b in c)

async def t1():
    agent = mod.VisaInfoAgent(name="V", model=None)
    msg = await agent.reply(type("M", (), {"content": "去日本旅游办什么签证，能待多久？"})())
    data = json.loads(content_of(msg))
    print("T1 status:", data["status"])
    print("T1 sources:", [(s["file"], s["path"][:40]) for s in data["sources"]])
    print("T1 answer:", data["answer"][:150].replace("\n", " / "))

class Stub:
    async def __call__(self, messages):
        text = messages[-1]["content"]
        if "候选节点" in text:
            return type("R", (), {"content": json.dumps({"selected": ["01#h1-1"], "expand": True, "confidence": 0.9})})()
        if "文档列表" in text:
            return type("R", (), {"content": json.dumps({"doc_ids": ["01_japan_visa"], "confidence": 0.9})})()
        if "知识原文" in text:
            return type("R", (), {"content": json.dumps({"answer": "单次旅游签证有效期5个月，停留30天。", "proactive_question": "需要材料清单吗？"})})()
        return type("R", (), {"content": "{}"})()

async def t2():
    agent = mod.VisaInfoAgent(name="V", model=Stub())
    msg = await agent.reply(type("M", (), {"content": "日本签证能停留多久"})())
    data = json.loads(content_of(msg))
    print("T2 answer:", data["answer"][:80])
    print("T2 number_check:", data["number_check"], "| proactive:", data["proactive_question"])

async def main():
    await t1(); print("-" * 50); await t2()
asyncio.run(main())
