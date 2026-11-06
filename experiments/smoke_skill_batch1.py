# -*- coding: utf-8 -*-
"""批次1（currency/translation/expense/memory/preference）消息层改造冒烟。

注意：utils.llm_response.extract_llm_json 在当前工作树被并发改动删除（HEAD 中存在），
本脚本在内存中注入同名桩函数，仅用于验证消息层替换，不修改任何文件。
"""
import asyncio, importlib.util as u, json, sys, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import utils.llm_response as _lr
if not hasattr(_lr, "extract_llm_json"):
    def _stub(response, fallback=None):
        if fallback is not None:
            return fallback
        return {"error": "stub"}
    _lr.extract_llm_json = _stub

SPECS = [
    ("currency", ".claude/skills/currency-converter/script/agent.py", "CurrencyConverterAgent"),
    ("translation", ".claude/skills/translation/script/agent.py", "TranslationAgent"),
    ("expense", ".claude/skills/expense-tracker/script/agent.py", "ExpenseTrackerAgent"),
    ("memory", ".claude/skills/memory-query/script/agent.py", "MemoryQueryAgent"),
    ("preference", ".claude/skills/preference/script/agent.py", "PreferenceAgent"),
]
OUT = Path("experiments/smoke_result.json")


def load(key, path, cls):
    spec = u.spec_from_file_location("skill_" + key, str(ROOT / path))
    mod = u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, cls)


async def main():
    from agentscope.message import Msg
    payload = Msg(name="Orchestrator", content=json.dumps({"context": {"rewritten_query": "测试查询"}}, ensure_ascii=False), role="user")
    plain = Msg(name="Orchestrator", content="你好", role="user")
    res = {}
    for key, path, cls in SPECS:
        try:
            A = load(key, path, cls)
            agent = A(model=None)
        except Exception:
            res[key] = {"load_error": traceback.format_exc()[-400:]}
            continue
        for label, x in (("payload", payload), ("plain", plain)):
            try:
                r = await agent.reply(x)
                c = r.content
                info = {"type": type(c).__name__, "is_str": isinstance(c, str)}
                if isinstance(c, str):
                    try:
                        d = json.loads(c)
                        info["json_keys"] = sorted(d.keys())[:8] if isinstance(d, dict) else "non-dict"
                    except Exception:
                        info["json"] = "invalid"
                res[key + "." + label] = info
            except Exception:
                res[key + "." + label] = {"exception": traceback.format_exc()[-400:]}
    try:
        A = load("memory", SPECS[3][1], SPECS[3][2])
        r = await A(model=None).reply([])
        res["memory.emptylist"] = {"content": r.content[:120]}
    except Exception:
        res["memory.emptylist"] = {"exception": traceback.format_exc()[-300:]}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


try:
    asyncio.run(main())
except Exception:
    OUT.write_text(json.dumps({"fatal": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")