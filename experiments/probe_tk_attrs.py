import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from agentscope.tool import Toolkit
from agentscope.skill import LocalSkillLoader

async def main():
    tk = Toolkit(tools=[], skills_or_loaders=[LocalSkillLoader(".claude/skills", scan_subdir=True)])
    print("attrs:", [a for a in vars(tk) if not a.startswith("__")])
    for a, v in vars(tk).items():
        if isinstance(v, (list, dict)):
            print(f"  {a}: {type(v).__name__} len={len(v)}")
    names = [a for a in dir(tk) if "skill" in a.lower()]
    print("skill-ish attrs/methods:", names)

asyncio.run(main())
