"""
测试事项收集智能体
"""
import sys
import os
import asyncio
import json
import importlib.util

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from agentscope.message import Msg
from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG

# importlib 加载避免模块名冲突
_spec = importlib.util.spec_from_file_location(
    "event_collection_agent",
    os.path.join(project_root, 'skills', 'event-collection', 'script', 'agent.py'),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
EventCollectionAgent = _mod.EventCollectionAgent


async def test_event_collection_agent():
    """测试事项收集智能体"""

    print("初始化 AgentScope...")
    init_agentscope()

    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
            stream=False,
        client_kwargs={"base_url": LLM_CONFIG["base_url"]},
        generate_kwargs={
            "temperature": LLM_CONFIG.get("temperature", 0.7),
            "max_tokens": LLM_CONFIG.get("max_tokens", 2000),
        },
    )

    agent = EventCollectionAgent(
        name="EventCollectionAgent",
        model=model
    )

    test_cases = [
        "我要从北京去上海出差3天",
        "下周一从杭州出发去深圳，周五回来",
        "去上海玩",  # 信息不完整的情况
        "3月15日从北京到上海，3月18日返回北京，出差",
    ]

    passed = 0
    failed = 0

    for i, query in enumerate(test_cases, 1):
        print("\n" + "="*70)
        print(f"测试 {i}")
        print("="*70)
        print(f"用户查询: {query}")
        print()

        try:
            msg = Msg(name="User", content=query, role="user")
            result = await agent.reply(msg)

            # 解析JSON结果
            content = json.loads(result.content) if isinstance(result.content, str) else result.content

            print("【提取结果】")

            if content.get("origin"):
                print(f"  [OK] 出发地: {content['origin']}")
            if content.get("destination"):
                print(f"  [OK] 目的地: {content['destination']}")
            if content.get("start_date"):
                print(f"  [OK] 出发日期: {content['start_date']}")
            if content.get("end_date"):
                print(f"  [OK] 返程日期: {content['end_date']}")
            if content.get("duration_days"):
                print(f"  [OK] 行程天数: {content['duration_days']}天")
            if content.get("return_location"):
                print(f"  [OK] 返程地: {content['return_location']}")
            if content.get("trip_purpose"):
                print(f"  [OK] 行程目的: {content['trip_purpose']}")

            extracted = content.get('extracted_count', 0)
            print(f"\n  已提取: {extracted}/7 项信息")

            if content.get("missing_info"):
                print(f"  [WARN] 缺失信息: {', '.join(content['missing_info'])}")

            if content.get("error"):
                print(f"  [ERROR] {content['error']}")
                failed += 1
            else:
                passed += 1
                print("  [PASS] 测试通过")

        except Exception as e:
            print(f"  [ERROR] 测试异常: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*70)
    print(f"测试结果: {passed}/{passed+failed} 通过")
    print("="*70)


if __name__ == "__main__":
    print("="*70)
    print("事项收集智能体测试")
    print("="*70)
    asyncio.run(test_event_collection_agent())
    print("\n测试完成！")
