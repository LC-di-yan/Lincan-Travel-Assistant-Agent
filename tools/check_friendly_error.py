"""离线验证：上游 403 时，行程智能体给用户的是人话，不是一坨 JSON。

不连网络、不起服务，直接喂一个会抛 403 的假模型。
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402


def load_agent_module(skill_name: str, class_name: str):
    """和 lazy_agent_registry 一样，按文件路径懒加载 skill 里的 Agent 类。"""
    path = ROOT / ".claude" / "skills" / skill_name / "script" / "agent.py"
    spec = importlib.util.spec_from_file_location(f"{skill_name}_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


ItineraryPlanningAgent = load_agent_module("plan-trip", "ItineraryPlanningAgent")

PAYLOAD = json.dumps({
    "user_query": "明天从北京去上海出差3天，预算2000",
    "context": {"rewritten_query": "明天从北京去上海出差3天，预算2000",
                "event_collection": {"origin": "北京", "destination": "上海", "duration_days": 3}},
}, ensure_ascii=False)


class DeniedModel:
    async def __call__(self, *args, **kwargs):
        raise Exception(
            "Error code: 403 - {'error': {'message': 'Access to model denied. "
            "'type': 'AccessDenied.Unpurchased', 'code': 'AccessDenied.Unpurchased'}}"
        )


async def main() -> int:
    from agentscope.message import Msg

    agent = ItineraryPlanningAgent(name="ItineraryPlanningAgent", model=DeniedModel())
    msg = await agent.reply(Msg(name="Orchestrator", content=PAYLOAD, role="user"))
    result = json.loads(msg.content)

    err = result.get("error", "")
    print("error      :", err)
    print("error_code :", result.get("error_code"))
    print("complete   :", result.get("planning_complete"))

    leaks = [bad for bad in ("AccessDenied", "403", "qianwen", "sk-") if bad in err]
    checks = {
        "有人话": "无法生成" in err,
        "未泄露上游细节": not leaks,
        "错误码可定位": result.get("error_code") == "entitlement",
        "planning_complete=False": result.get("planning_complete") is False,
        "无 technical_error": "technical_error" not in result,
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
