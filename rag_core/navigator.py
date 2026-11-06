# -*- coding: utf-8 -*-
"""树导航器（navigator）：L1 文档路由 + L2 树内下钻。

设计（方案 §6.3）：
- L1 规则直通优先：关键词命中 manifest 卡片 → 零 LLM 调用；
- L2 最多下钻 2 层，每层让 LLM 从候选节点的 {id,title,summary} 里选 0-2 个；
- 置信度 < floor / 异常 / 无模型 → degraded=True，调用方走 BM25 兜底；
- 单问题导航 LLM 调用 ≤ max_llm_calls（默认 2）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from utils.llm_response import extract_json_object, extract_llm_text

logger = logging.getLogger(__name__)

CONFIDENCE_FLOOR = 0.6
MAX_DEPTH = 2
CALL_TIMEOUT = 8.0

# 城市档位是领域常识：把「杭州」这类问题直接映射到「二线城市」章节，省掉一次 LLM 导航
CITY_TIER = {
    "北京": "一线城市", "上海": "一线城市", "广州": "一线城市", "深圳": "一线城市",
    "杭州": "二线城市", "南京": "二线城市", "成都": "二线城市", "武汉": "二线城市", "西安": "二线城市",
}

EXTRA_TERMS = {
    "01_travel_standards": ["标准", "住宿", "舱位", "高铁", "补贴", "餐饮", "额度", "上限", "几等座", "商务座", "经济舱", "二等座"],
    "02_reimbursement_policy": ["报销", "发票", "凭证", "票据", "抬头", "税号", "逾期", "行程单"],
    "03_booking_guide": ["预订", "订票", "订机票", "订酒店", "值机", "选座", "退票", "改签", "客服电话", "提前多久"],
    "04_faq": ["怎么办", "可以吗", "能不能", "家属", "驳回", "私家车"],
    "05_emergency_procedures": ["延误", "取消", "紧急", "丢失", "遗失", "事故", "突发", "证明"],
    "06_platform_guide": ["平台", "商旅系统", "app", "网址", "功能", "客服"],
    "07_city_specific_tips": ["北京", "上海", "广州", "深圳", "成都", "杭州", "南京", "武汉", "西安", "机场", "地铁", "出租", "起步价"],
    "08_environmental_initiatives": ["环保", "低碳", "碳排放", "绿色"],
}


@dataclass
class NavHit:
    doc_id: str
    node_id: str
    path: str
    source: str  # rule / llm / leaf


@dataclass
class NavResult:
    hits: List[NavHit] = field(default_factory=list)
    llm_calls: int = 0
    elapsed_ms: int = 0
    degraded: bool = False
    reason: str = ""


def _title_matches(query: str, title: str) -> bool:
    """标题与问题的重合判定（免 LLM 的直通道）。"""
    clean = _strip_num(title)
    q = query.strip()
    if not clean or len(clean) < 3:
        return False
    if clean in q or q in clean:
        return True
    # 同义词根：丢失/遗失/丢（如「火车票丢了」↔「票据遗失处理」）
    stems = ("丢", "遗失", "延误", "取消")
    if any(s in clean and s in q for s in stems):
        return True
    # 只看连续子串（4 字优先，再 3 字）；字符集合重叠太松（「飞机标准」会因共享「标准」误命中）
    for w in (4, 3):
        if len(clean) >= w:
            for i in range(len(clean) - w + 1):
                if clean[i:i + w] in q:
                    return True
    return False


def _strip_num(title: str) -> str:
    import re
    return re.sub(r"^(Q\d+\s*[:：]|[一二三四五六七八九十]+、|\d+[\.、])\s*", "", title or "").strip()


class Navigator:
    def __init__(self, tree_store, model=None, max_llm_calls: int = 2,
                 confidence_floor: float = CONFIDENCE_FLOOR, timeout: float = CALL_TIMEOUT,
                 use_llm: bool = True):
        self.store = tree_store
        self.model = model
        self.use_llm = use_llm and model is not None
        self.max_llm_calls = max(1, int(max_llm_calls))
        self.confidence_floor = float(confidence_floor)
        self.timeout = float(timeout)
        self._rule_cache: Optional[List[Tuple[str, List[str]]]] = None
        self._bm25 = None

    # ── L1：文档路由 ────────────────────────────────────────
    def _rules(self) -> List[Tuple[str, List[str]]]:
        if self._rule_cache is None:
            self._rule_cache = [
                (c["doc_id"], list(c.get("keywords", [])) + EXTRA_TERMS.get(c["doc_id"], []))
                for c in self.store.manifest_cards()
            ]
        return self._rule_cache

    def route_by_rules(self, query: str) -> List[str]:
        """关键词命中最多的 1-2 篇；无命中返回 []。"""
        if not query.strip():
            return []
        scored = []
        for doc_id, kws in self._rules():
            score = sum(1 for kw in kws if kw and kw in query)
            if score:
                scored.append((score, doc_id))
        if not scored:
            return []
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = scored[0][0]
        return [d for s, d in scored if s >= max(1, top - 1)][:2]

    async def _llm_route(self, query: str) -> Tuple[List[str], float]:
        cards = self.store.manifest_cards()
        lines = "\n".join(f"- {c['doc_id']}｜{c['title']}｜{c['summary']}" for c in cards)
        prompt = (
            "从下列知识文档中选出最可能包含答案的 1-2 篇。\n"
            f"问题：{query}\n\n【文档列表】\n{lines}\n\n"
            '只输出 JSON：{"doc_ids": ["..."], "confidence": 0到1}'
        )
        data = await self._ask(prompt)
        if not data:
            return [], 0.0
        ids = [d for d in (data.get("doc_ids") or []) if d in self.store.docs]
        return ids[:2], float(data.get("confidence", 0.5) or 0.5)

    # ── L2：树内下钻 ────────────────────────────────────────
    def _line(self, node) -> str:
        return f"- {node.id}｜{node.title}｜{node.summary}"

    async def descend(self, query: str, doc_id: str, calls: int = 0,
                      allow_llm: bool = True) -> Tuple[List[NavHit], int, bool]:
        doc = self.store.docs.get(doc_id)
        if not doc:
            return [], calls, True
        hits: List[NavHit] = []
        candidates = doc.tree
        depth = 0
        while candidates and depth < MAX_DEPTH:
            # 规则直通道：标题直接命中问题 → 选中并下钻其子节点（不再花 LLM）
            rule_hits = [c for c in candidates if _title_matches(query, c.title)]
            if not rule_hits and depth == 0:
                # 无标题直命中时：对全部章节按「问题 ∩ (标题+摘要+子标题) 的 bigram 重叠」打分，取 top2。
                # 不要求标题前两字命中——「私家车/家属」这类词只在子标题里。
                def _score(c) -> int:
                    blob = c.title + " " + c.summary + " " + " ".join(
                        x.title + " " + x.summary for x in c.children)
                    return sum(1 for i in range(len(query) - 1) if query[i:i + 2] in blob)
                ranked = sorted(((c, _score(c)) for c in candidates), key=lambda x: -x[1])
                picked = [c for c, sc in ranked if sc >= 2][:2]
                if picked:
                    for c in picked:
                        sub = [x for x in c.children if _title_matches(query, x.title)]
                        if sub:
                            for s in sub[:3]:
                                hits.append(NavHit(doc_id, s.id, self.store.path_of(doc_id, s.id), "rule"))
                        else:
                            hits.append(NavHit(doc_id, c.id, self.store.path_of(doc_id, c.id), "rule"))
                    return hits, calls, False
            if rule_hits:
                for c in rule_hits:
                    if c.children and depth + 1 < MAX_DEPTH:
                        sub = [x for x in c.children if _title_matches(query, x.title)]
                        if sub:
                            for s in sub:
                                hits.append(NavHit(doc_id, s.id, self.store.path_of(doc_id, s.id), "rule"))
                            return hits, calls, False
                        candidates = c.children          # 继续在该章节内下钻一层
                        depth += 1
                        break
                    hits.append(NavHit(doc_id, c.id, self.store.path_of(doc_id, c.id), "rule"))
                if hits:
                    return hits, calls, False
                continue
            if calls >= self.max_llm_calls or not self.use_llm or not allow_llm:
                return hits, calls, True
            calls += 1
            lines = "\n".join(self._line(c) for c in candidates[:14])
            prompt = (
                "在文档章节中选出最可能包含答案的节点（0-2 个）。\n"
                f"问题：{query}\n\n【候选节点】\n{lines}\n\n"
                "若某节点标题已直接命中问题主题，选它并置 expand=false。"
                "不要解释过程，直接输出 JSON："
                '{"selected": ["id"], "expand": true/false, "confidence": 0到1}'
            )
            data = await self._ask(prompt)
            if not data:
                return hits, calls, True
            valid = {c.id: c for c in candidates}
            sel = [s for s in (data.get("selected") or []) if s in valid]
            conf = float(data.get("confidence", 0.5) or 0.5)
            if conf < self.confidence_floor or not sel:
                return hits, calls, True
            expand = bool(data.get("expand"))
            children = []
            for s in sel:
                children.extend(valid[s].children)
            if not expand or not children:
                for s in sel:
                    hits.append(NavHit(doc_id, s, self.store.path_of(doc_id, s), "llm"))
                return hits, calls, False
            candidates = children
            depth += 1
        # 层级用尽仍未定稿：把当前候选交给生成阶段
        for c in candidates[:3]:
            hits.append(NavHit(doc_id, c.id, self.store.path_of(doc_id, c.id), "leaf"))
        return hits, calls, False

    async def _ask(self, prompt: str) -> Optional[dict]:
        if not self.use_llm:
            return None
        try:
            resp = await asyncio.wait_for(
                self.model([
                    {"role": "system", "content": "你是文档检索导航器，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ]),
                timeout=self.timeout,
            )
            return extract_json_object(extract_llm_text(resp, ""))
        except asyncio.TimeoutError:
            logger.warning("导航 LLM 超时（%.1fs）", self.timeout)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("导航 LLM 失败：%s", exc)
            return None

    # ── 主入口 ─────────────────────────────────────────────
    @staticmethod
    def expand_query(query: str) -> str:
        """把城市名展开成档位词（杭州 → 杭州 二线城市），提升规则/词面命中率。"""
        extra = [tier for city, tier in CITY_TIER.items() if city in query]
        return query + (" " + " ".join(dict.fromkeys(extra)) if extra else "")

    async def navigate(self, query: str) -> NavResult:
        query = self.expand_query(query)
        t0 = time.time()
        result = NavResult()
        try:
            rule_docs = self.route_by_rules(query)
            doc_ids = list(rule_docs)
            # BM25 文档投票：补充规则没覆盖到的文档，但这些文档只走词面（不花 LLM）
            try:
                from .bm25_fallback import BM25Fallback
                bm = self._bm25 or BM25Fallback(self.store)
                self._bm25 = bm
                for r in bm.search(query, top_k=3):
                    if r["doc_id"] not in doc_ids:
                        doc_ids.append(r["doc_id"])
                doc_ids = doc_ids[:3]
            except Exception as exc:  # noqa: BLE001
                logger.debug("BM25 路由投票不可用：%s", exc)
            if not doc_ids:
                if self.model is None:
                    result.degraded, result.reason = True, "no_model"
                    result.elapsed_ms = int((time.time() - t0) * 1000)
                    return result
                doc_ids, conf = await self._llm_route(query)
                result.llm_calls += 1
                if not doc_ids or conf < self.confidence_floor:
                    result.degraded, result.reason = True, "route_low_confidence"
                    result.elapsed_ms = int((time.time() - t0) * 1000)
                    return result
            for doc_id in doc_ids:
                start = result.llm_calls
                hits, used, degraded = await self.descend(
                    query, doc_id, calls=start, allow_llm=(doc_id in rule_docs))
                result.llm_calls = max(start, used)
                result.hits.extend(hits)
                if degraded and not result.reason:
                    result.reason = "descend_low_confidence"
            # 只要有命中就不算降级（部分文档失败不影响整体结果）
            result.degraded = not result.hits
        except Exception as exc:  # noqa: BLE001
            logger.warning("导航异常，降级：%s", exc)
            result.degraded, result.reason = True, f"error:{exc}"
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result