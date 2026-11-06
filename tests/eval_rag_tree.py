# -*- coding: utf-8 -*-
"""树导航检索离线评测（CI 门禁脚本，不联网、不需要 LLM）。

跑法：
  python tests/eval_rag_tree.py          # 离线模式（规则导航 ∪ BM25）
  python tests/eval_rag_tree.py -v       # 打印逐题细节

测的是 RAGKnowledgeAgent.retrieve()——与线上同一条检索路径，只是没有 LLM。
判定标准 = 标准答案串是否出现在 top-k 检索结果原文里。
说明：线上接入 LLM 导航后指标应不低于此；本脚本是「无 LLM 最坏情况」的回归门禁。
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "rag_agent_eval", ROOT / ".claude" / "skills" / "ask-question" / "script" / "agent.py")
rag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rag)

QUERIES = [
    ("一线城市出差住宿标准是多少", "不超过500元/晚", "01"),
    ("杭州住宿费上限是多少", "不超过400元/晚", "01"),
    ("三线城市住宿标准", "不超过300元/晚", "01"),
    ("高铁可以坐商务座吗", "可申请商务座", "01"),
    ("国际长途航班能坐什么舱位", "高端经济舱", "01"),
    ("出差申请要提前几天提交", "至少3个工作日", "01"),
    ("机票提前多久订比较便宜", "建议提前7-14天预订", "03"),
    ("国际机票建议提前多久订", "建议提前21-30天预订", "03"),
    ("商旅平台客服电话是多少", "400-800-8888", "03"),
    ("在线值机什么时候开放", "起飞前24小时开放", "03"),
    ("报销要在多长时间内提交", "30个自然日内提交报销申请", "02"),
    ("12月出差最晚什么时候报销", "次年1月15日", "02"),
    ("发票抬头要开成什么", "阿里巴巴（中国）有限公司", "02"),
    ("火车票丢了怎么报销", "报销凭证", "02"),
    ("住宿发票需要什么类型", "增值税发票", "02"),
    ("航班延误多久可以考虑改签", "超过4小时", "05"),
    ("航班取消了该怎么处理", "了解取消原因和退改方案", "05"),
    ("延误证明向谁索取", "向航空公司或机场索取", "05"),
    ("出差申请被驳回了怎么办", "查看驳回原因", "04"),
    ("临时要延长出差时间怎么办", "行程变更申请", "04"),
    ("可以自己开私家车出差吗", "油费、过路费、停车费", "04"),
    ("出差打车有什么规定", "允许打车的场景", "04"),
    ("首都机场离市中心多远", "距市中心约25公里", "07"),
    ("北京出租车起步价是多少", "起步价14元", "07"),
    ("大兴机场线到草桥要几分钟", "20分钟到草桥", "07"),
    ("多少公里以内优先坐高铁", "优先选择高铁", "08"),
    ("高铁比飞机碳排放低多少", "碳排放量降低约90%", "08"),
    ("阿里商旅平台网址是什么", "travel.alibaba.com", "06"),
    ("出差可以带家属吗", "家属随行产生的所有费用", "04"),
    ("行李托运费能报销吗", "行李托运费", "04"),
    ("国内航班要提前多久到机场", "提前1.5小时", "03"),
    ("上海浦东机场离市区多远", "距市中心约40公里", "07"),
    ("发票丢了还能报销吗", "遗失说明", "02"),
    ("出差补贴怎么算", "出差补贴", "01"),
    ("怎么参与碳补偿计划", "碳补偿计划", "08"),
    ("同事一起出差能拼车吗", "拼车", "08"),
    ("平台上能订租车吗", "租车服务", "06"),
    ("报销需要哪些材料", "必需材料清单", "02"),
    ("被拒绝的申请怎么重新提交", "修改后重新提交", "04"),
    ("晚上出行可以坐卧铺吗", "可选择卧铺", "01"),
]

TOPK = 3


def run(verbose: bool = False, use_llm: bool = False) -> dict:
    model = None
    if use_llm:
        from config_agentscope import init_agentscope
        from config import LLM_CONFIG
        from utils.as_compat import build_chat_model
        init_agentscope()
        model = build_chat_model({
            "model_name": LLM_CONFIG["model_name"],
            "api_key": LLM_CONFIG["api_key"],
            "base_url": LLM_CONFIG["base_url"],
            "client_kwargs": {"timeout": 60},
            "generate_kwargs": {"temperature": 0.2, "max_tokens": 2048},
        }, stream=False)
    agent = rag.RAGKnowledgeAgent(name="eval", model=model)
    if not rag._get_tree_store().loaded:
        raise SystemExit("树索引不可用：" + "; ".join(rag._get_tree_store().errors[:3]))

    records = []
    for q, ev, doc in QUERIES:
        docs = asyncio.run(agent.retrieve(q, top_k=4))
        rank = None
        for i, d in enumerate(docs):
            if ev.replace(" ", "") in d["text"].replace(" ", ""):
                rank = i + 1
                break
        records.append({"q": q, "expect": doc, "rank": rank,
                        "meta": getattr(agent, "_last_retrieval", {})})

    n = len(records)
    hit1 = sum(1 for r in records if r["rank"] == 1) / n
    hit3 = sum(1 for r in records if r["rank"] and r["rank"] <= 3) / n
    hit4 = sum(1 for r in records if r["rank"] and r["rank"] <= 4) / n
    mrr = sum((1.0 / r["rank"]) if r["rank"] else 0.0 for r in records) / n
    nav_used = sum(1 for r in records if r["meta"].get("nav_hits"))

    avg_ms = sum(r["meta"].get("ms", 0) for r in records) / n
    calls = sum(r["meta"].get("calls", 0) for r in records) / n
    print(f"题数={n}  模式={'LLM导航' if use_llm else '离线(无LLM)'}  Hit@1={hit1:.3f}  Hit@3={hit3:.3f}  "
          f"Hit@4={hit4:.3f}  MRR={mrr:.3f}  树导航参与={nav_used}/{n}  平均导航耗时={avg_ms:.0f}ms  LLM调用/题={calls:.2f}")
    fails = [r for r in records if not r["rank"]]
    if fails:
        print("\n未命中：")
        for r in fails:
            print(f"  - [{r['expect']}] {r['q']}  nav={r['meta'].get('nav_hits')} bm25={r['meta'].get('bm25_hits')}")
    if verbose:
        print("\n逐题：")
        for r in records:
            mark = "✓" if r["rank"] == 1 else ("~" if r["rank"] else "✗")
            print(f"  {mark} rank={r['rank']} {r['q']}  [{r['expect']}]")
    return {"n": n, "hit@1": hit1, "hit@3": hit3, "mrr": mrr}


if __name__ == "__main__":
    run(verbose="-v" in sys.argv, use_llm="--llm" in sys.argv)