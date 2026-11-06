import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from agents.skill_toolkit import build_skill_toolkit

async def main():
    # 默认路径：agents=None → LazyAgentRegistry 真实装载（model=None，不触网）
    tk = await build_skill_toolkit(model=None)
    got = 0
    for name in ["translation", "hotel-search", "place-search", "train-ticket", "ask-question", "plan-trip",
                 "visa-info", "memory-query", "expense-tracker", "currency-converter", "preference",
                 "query-info", "event-collection"]:
        if await tk.get_tool(name) is not None:
            got += 1
    print(f"tools registered: {got}/13")
    skills = await tk._get_available_skills()
    print(f"instructions loaded: {len(skills)}/13")

asyncio.run(main())
