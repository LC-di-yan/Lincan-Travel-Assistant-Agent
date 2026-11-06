import asyncio, inspect, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from agentscope.tool import Toolkit
from agentscope.skill import LocalSkillLoader

async def main():
    tk = Toolkit(tools=[], skills_or_loaders=[LocalSkillLoader(".claude/skills", scan_subdir=True)])
    sig = inspect.signature(tk._get_available_skills)
    print("_get_available_skills:", sig)
    skills = await tk._get_available_skills()
    print("count:", len(skills), "names:", [s.name for s in skills])
    # skill_viewer 工具名
    sv = tk.builtin_skill_viewer
    print("skill_viewer tool name:", getattr(sv, "name", None))

asyncio.run(main())
