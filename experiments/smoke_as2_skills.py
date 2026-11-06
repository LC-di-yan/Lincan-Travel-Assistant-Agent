import asyncio, importlib.util, inspect, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))
from agents.base import SkillAgentBase
from utils.as_compat import msg_text, msg_json

FILES = [
    ".claude/skills/currency-converter/script/agent.py",
    ".claude/skills/translation/script/agent.py",
    ".claude/skills/expense-tracker/script/agent.py",
    ".claude/skills/memory-query/script/agent.py",
    ".claude/skills/preference/script/agent.py",
    ".claude/skills/plan-trip/script/agent.py",
    ".claude/skills/plan-trip/script/plan_trip_execution.py",
    ".claude/skills/event-collection/script/agent.py",
    ".claude/skills/visa-info/script/agent.py",
    ".claude/skills/ask-question/script/agent.py",
]

async def main():
    ok, fail = 0, 0
    for f in FILES:
        try:
            spec = importlib.util.spec_from_file_location("m_" + Path(f).parent.parent.name.replace("-", "_"), f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            classes = [o for _, o in inspect.getmembers(mod, inspect.isclass)
                       if issubclass(o, SkillAgentBase) and o is not SkillAgentBase]
            if not classes:
                print(f"SKIP  {f}  (no SkillAgentBase subclass)")
                continue
            cls = classes[0]
            inst = cls(name="smoke", model=None)
            res = await inst.reply(None)
            text = msg_text(res)
            parsed = msg_json(res, default={"__unparsed__": True})
            kind = type(res).__name__
            print(f"OK    {f.split('skills/')[1]:38s} {cls.__name__:24s} {kind:8s} text_len={len(text):3d} json={'yes' if '__unparsed__' not in parsed else 'NO'}")
            ok += 1
        except Exception as e:
            print(f"FAIL  {f.split('skills/')[1]:38s} {type(e).__name__}: {str(e)[:110]}")
            fail += 1
    print(f"\nsummary: ok={ok} fail={fail}")

asyncio.run(main())
