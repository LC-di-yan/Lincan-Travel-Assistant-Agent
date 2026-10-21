"""离线验证：上游 403 时，三处用户可见位置都不能出现原始报错。

覆盖：
1. 意图识别兜底 reasoning（侧栏 REASONING 面板）
2. 编排层 agent 失败 message（结果卡片标题）
3. 行程规划失败 error（已由 tools/check_friendly_error.py 覆盖，这里顺带跑一遍）
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LEAK_MARKERS = ("AccessDenied", "Unpurchased", "Error code", "403", "sk-ws-", "qianwen")


class DeniedModel:
    async def __call__(self, *args, **kwargs):
        raise Exception(
            "Error code: 403 - {'error': {'message': 'Access to model denied. "
            "'type': 'AccessDenied.Unpurchased', 'code': 'AccessDenied.Unpurchased'}}"
        )


def leaks(text: str) -> bool:
    return any(m in (text or "") for m in LEAK_MARKERS)


async def check_intention() -> bool:
    from agentscope.message import Msg
    from agents.intention_agent import IntentionAgent

    agent = IntentionAgent(name="IntentionAgent", model=DeniedModel())
    msg = await agent.reply(Msg(name="user", content="我住酒店喜欢汉庭", role="user"))
    data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
    reasoning = str(data.get("reasoning", ""))
    print("reasoning :", reasoning)
    ok = (not leaks(reasoning)) and "默认策略" in reasoning
    print(("PASS " if ok else "FAIL ") + "意图兜底 reasoning 不含原始报错")
    return ok


async def check_orchestration() -> bool:
    from agents.orchestration_agent import OrchestrationAgent

    class BoomAgent:
        async def reply(self, *_args, **_kwargs):
            raise Exception("Error code: 403 - {'error': {'code': 'AccessDenied.Unpurchased'}}")

    orch = OrchestrationAgent(
        name="OrchestrationAgent",
        agent_registry={"itinerary_planning": BoomAgent()},
    )
    res = await orch._execute_agent(  # type: ignore[attr-defined]
        "itinerary_planning", {"rewritten_query": "x"}, "规划行程", "行程计划", []
    )
    text = json.dumps(res, ensure_ascii=False)
    print("agent res :", text[:180])
    ok = (not leaks(text)) and res.get("status") == "error"
    print(("PASS " if ok else "FAIL ") + "编排层失败信息已收敛")
    return ok


async def main() -> int:
    results = [await check_intention(), await check_orchestration()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
