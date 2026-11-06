import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from agents.base import SkillAgentBase
from agents.skill_toolkit import build_skill_toolkit
from utils.as_compat import mk_msg, msg_json

class Fake(SkillAgentBase):
    async def reply(self, x=None, **kw):
        return mk_msg(self.name, {"ok": True, "echo": msg_json(x, default={})})

async def main():
    tk = await build_skill_toolkit(names=["translation"], agents={"translation": Fake(name="translation")})
    avail = tk._get_available_skills()
    print("available type:", type(avail).__name__, "value:", repr(avail)[:200])

    from agentscope.message import ToolCallBlock
    from agentscope.state import AgentState
    call = ToolCallBlock(type="tool_call", id="c1", name="translation", input=json.dumps({"payload": {"text": "hi"}}))
    print("call.input:", repr(call.input)[:80])
    state = AgentState(session_id="s")
    async for item in tk.call_tool(call, state):
        print("CHUNK:", type(item).__name__, "| content:", repr(getattr(item, "content", None))[:300])
        print("  metadata:", repr(getattr(item, "metadata", None))[:120])

asyncio.run(main())
