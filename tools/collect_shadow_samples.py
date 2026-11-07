# -*- coding: utf-8 -*-
"""影子样本采集：跑真实 IntentionAgent.reply()，产出成对 decision/outcome 记录。

用途：为「shadow → assist 提升」提供真实一致率依据（tools/replay_shadow.py）。
注意：走完整生产链路（快路由 + LLM 路径都会落 outcome），不是直接调 engine.route。
"""
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from config import LLM_CONFIG
from agents.intention_agent import IntentionAgent
from utils.as_compat import build_chat_model, mk_msg, msg_json

QUERIES = [
    "帮我找杭州西湖附近的酒店",
    "上海有什么好吃的餐厅推荐",
    "北京有哪些值得去的景点",
    "查一下明天北京到上海的高铁票",
    "出差住宿费标准是多少",
    "差旅报销需要哪些材料",
    "我住酒店喜欢万豪，请记住",
    "帮我查一下我之前的差旅记录",
    "今天天气真不错啊",
    "100美元等于多少人民币",
    "把这句翻译成英文：会议改到下午三点",
    "去泰国需要签证吗",
    "记一下今天打车花了85元",
    "杭州下周天气怎么样",
    "我想去成都出差三天，帮我安排行程",
    "深圳南山区有没有便宜点的民宿",
    "广州塔附近有什么特色小吃",
    "从上海虹桥到苏州的火车票还有吗",
    "机票一般提前多久订比较便宜",
    "我喜欢靠窗的座位，以后都这样订",
    "这个月差旅一共花了多少钱",
    "日本签证有效期是多久",
    "嗯嗯我知道了",
    "帮我把酒店预订确认单翻译成中文",
]

async def main():
    model = build_chat_model({
        "model_name": LLM_CONFIG["model_name"],
        "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"],
        "generate_kwargs": {"temperature": LLM_CONFIG.get("temperature", 0.7)},
    })
    agent = IntentionAgent(name="ShadowCollector", model=model)
    ok = err = 0
    t0 = time.monotonic()
    for i, q in enumerate(QUERIES, 1):
        try:
            res = await agent.reply(mk_msg("user", q, role="user"))
            data = msg_json(res, default={}) or {}
            intents = [x.get("type") for x in data.get("intents", [])]
            print(f"[{i}/{len(QUERIES)}] OK  {q[:24]}  intents={intents}", flush=True)
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(QUERIES)}] ERR {q[:24]}  {type(e).__name__}: {str(e)[:80]}", flush=True)
            err += 1
        await asyncio.sleep(0.3)
    # 等影子异步任务落盘
    await asyncio.sleep(6)
    print(f"DONE ok={ok} err={err} elapsed={time.monotonic()-t0:.0f}s", flush=True)

asyncio.run(main())