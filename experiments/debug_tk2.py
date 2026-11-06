import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from agents.base import SkillAgentBase
from agents.skill_toolkit import build_skill_toolkit
from utils.as_compat import mk_msg, msg_json

class Fake(SkillAgentBase):
    async def reply(self, x=None, **kw):
        return mk_msg(self.name, {"ok": True})

async def main():
    tk = await build_skill_toolkit(names=["translation"], agents={"translation": Fake(name="translation")})
    avail = await tk._get_available_skills()
    print("available:", type(avail).__name__, repr(avail)[:160])

    from agentscope.message import ToolCallBlock
    from agentscope.state import AgentState
    call = ToolCallBlock(type="tool_call", id="c1", name="translation", input=json.dumps({"payload": {"t": 1}}))
    state = AgentState(session_id="s")
    i = 0
    async for item in tk.call_tool(call, state):
        print(f"--- chunk {i}: {type(item).__name__} is_last={getattr(item,'is_last',None)} state={getattr(item,'state',None)}")
        for b in (getattr(item, 'content', None) or []):
            print("    block:", type(b).__name__, repr(getattr(b, 'text', None))[:120])
        i += 1

asyncio.run(main())
