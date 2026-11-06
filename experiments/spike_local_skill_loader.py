import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from agentscope.skill import LocalSkillLoader

async def main():
    loader = LocalSkillLoader(".claude/skills", scan_subdir=True)
    skills = await loader.list_skills()
    print("loaded:", len(skills))
    for s in skills:
        print(f"  {s.name:20s} dir={Path(s.dir).name:20s} md_len={len(s.markdown):5d}")

asyncio.run(main())
