#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
独立测试地点搜索 Agent（酒店/餐厅/景点）

功能：
- 使用高德 POI 搜索 API (place/text) 搜索酒店、餐厅、景点信息
- 测试城市提取、参数解析、API 调用、结果构建

依赖：
- AMAP_API_KEY 需在 .env 中配置
- agentscope 框架

使用方法：
  python test_hotel_search.py
"""
import sys
import os
import io
import asyncio
import json
import time
import importlib.util

# 修复 Windows 终端 GBK 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from agentscope.message import Msg
from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG, AMAP_CONFIG

_spec = importlib.util.spec_from_file_location(
    "place_search_agent",
    os.path.join(project_root, '.claude', 'skills', 'place-search', 'script', 'agent.py'),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PlaceSearchAgent = _mod.PlaceSearchAgent


def print_sep(title: str = ""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
    print(f"{'='*60}")


def print_hotel(hotel: dict, idx: int = 0):
    num = f"[{idx}]" if idx else ""
    print(f"  {num} {hotel['name']}")
    print(f"     Addr: {hotel.get('address', '-')}")
    rating = hotel.get('rating', '')
    cost = hotel.get('cost', '')
    if rating and cost:
        print(f"     Rating: {rating}  |  Cost: {cost}")
    elif rating:
        print(f"     Rating: {rating}")
    elif cost:
        print(f"     Cost: {cost}")
    tel = hotel.get('tel', '')
    if tel:
        print(f"     Tel: {tel}")
    dist = hotel.get('distance', '')
    if dist:
        print(f"     Distance: {dist}m")


async def test_single(agent, query: str, label: str = ""):
    print_sep(f"Query: {query}  [{label}]")
    start = time.time()

    msg = Msg(name="user", content=query, role="user")
    result = await agent.reply(msg)

    elapsed = (time.time() - start) * 1000
    data = json.loads(result.content) if isinstance(result.content, str) else result.content

    print(f"  Time: {elapsed:.0f}ms")
    print(f"  Type: {data.get('query_type', '?')}")
    print(f"  OK: {data.get('query_success', False)}")

    results = data.get("results", {})
    if data.get("query_success"):
        print(f"  City: {results.get('city', '?')}")
        print(f"  Keyword: {results.get('keyword', '?')}")
        print(f"  Count: {results.get('count', 0)}")

        summary = results.get("summary", "")
        if summary:
            print(f"\n  [Summary] {summary}")

        hotels = results.get("hotels", [])
        if hotels:
            print(f"\n  --- Hotel List (Top {len(hotels)}) ---")
            for i, h in enumerate(hotels, 1):
                print_hotel(h, i)
        else:
            print("  [WARN] No hotels found")

        pq = data.get("proactive_question", "")
        if pq:
            print(f"\n  [Proactive] {pq}")
    else:
        print(f"  [FAIL] {results.get('message', 'Unknown error')}")

    print()
    return data


async def main():
    print_sep("Place Search Agent - Independent Test")
    print(f"  AMAP_API_KEY: {'OK' if AMAP_CONFIG.get('api_key') else 'MISSING'}")

    if not AMAP_CONFIG.get("api_key"):
        print("\n  [ERROR] AMAP_API_KEY not set. Please configure in .env")
        return

    print("\n  Initializing agentscope...")
    init_agentscope()

    print("  Creating model...")
    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
        temperature=0.3,
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )

    agent = PlaceSearchAgent(name="PlaceSearchAgent", model=model)
    print("  Agent ready.")

    # ── Test cases ──
    test_cases = [
        ("北京有哪些酒店", "basic hotel search"),
        ("揭阳市揭东区锡场镇附近有酒店吗", "township-level search"),
        ("帮我找成都的民宿", "B&B search"),
        ("深圳五星级酒店", "star filter"),
        ("杭州西湖附近的客栈", "location keyword"),
        ("万豪酒店", "brand search (no city)"),
    ]

    for query, label in test_cases:
        await test_single(agent, query, label)
        await asyncio.sleep(0.5)

    print_sep("Test Complete")


if __name__ == "__main__":
    asyncio.run(main())
