# -*- coding: utf-8 -*-
"""P8 灰度双跑探针：输出当前解释器下的可比对 JSON（不依赖外部 LLM）。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def probe_version():
    import agentscope

    return {"version": agentscope.__version__, "has_init": hasattr(agentscope, "init")}


def probe_msg_contract():
    from utils.as_compat import AS_MAJOR, as_messages, mk_msg, msg_json, msg_text

    m = mk_msg("probe", {"a": 1, "b": "中文"})
    out = as_messages([{"role": "user", "content": "hi"}])
    return {
        "as_major": AS_MAJOR,
        "json_roundtrip": msg_json(m) == {"a": 1, "b": "中文"},
        "text": msg_text(mk_msg("u", "纯文本", role="user")),
        "msg_list_types": [type(x).__name__ for x in out],
    }


def probe_skills():
    try:
        from agentscope.skill import LocalSkillLoader

        async def run():
            return await LocalSkillLoader(str(ROOT / ".claude/skills"), scan_subdir=True).list_skills()

        skills = asyncio.run(run())
        return {"loader": "agentscope.skill.LocalSkillLoader", "count": len(skills), "names": sorted(s.name for s in skills)}
    except Exception as exc:
        return {"loader": "unavailable", "error": str(exc)[:120]}


def probe_smoke_skills():
    """已迁移 Skill 的工具注册数（仅 2.x 有意义；1.x 下优雅跳过）。"""
    from utils.as_compat import AS_MAJOR

    if AS_MAJOR < 2:
        return {"tools_registered": None, "note": "1.x 无 FunctionTool/ToolChunk 契约，跳过"}

    async def run():
        from agents.skill_toolkit import build_skill_toolkit

        tk = await build_skill_toolkit()
        names = ["translation", "hotel-search", "place-search", "train-ticket", "ask-question",
                 "plan-trip", "visa-info", "memory-query", "expense-tracker", "currency-converter",
                 "preference", "query-info", "event-collection"]
        found = 0
        for n in names:
            try:
                if await tk.get_tool(n) is not None:
                    found += 1
            except Exception:
                pass
        return found

    return {"tools_registered": asyncio.run(run())}


def main():
    report = {
        "version": probe_version(),
        "msg_contract": probe_msg_contract(),
        "skills": probe_skills(),
        "smoke_tools": probe_smoke_skills(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
