# -*- coding: utf-8 -*-
"""答案生成与数字校验（answerer）。

职责（方案 §6.5）：
- 把树导航/兜底命中的节点原文拼成知识上下文；
- 调 LLM 生成答案（沿用原 reply() 的 prompt 风格与 proactive_question 约定）；
- 「金额/比例/天数逐字摘自原文」的硬校验：带单位的数字必须在原文中逐字出现，
  未通过 → 带提示修复一次；仍失败 → 保留答案但在结果里打 number_check=failed 并提示用户核对。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.as_compat import as_messages
from utils.llm_response import extract_json_object, extract_llm_text

logger = logging.getLogger(__name__)

# 带「计量单位语境」的数字：只校验这些，避免把列表编号（1. 2.）误伤
# 形如 8-9折 / 4小时 / 500元 / 30个自然日；含区间（8-9折、7-14天）
UNIT_NUM_RE = re.compile(
    r"\d[\d,，]*(?:\.\d+)?\s*(?:[-—~至到]\s*\d[\d,，]*(?:\.\d+)?)?\s*"
    r"(?:元|万元|小时|天|日|个工作日|工作日|自然日|公里|千米|%|％|折|分钟|个月|人|座|米|公斤|斤|次|周)"
)


def _norm_num(tok: str) -> str:
    return tok.replace(",", "").replace("，", "").replace(" ", "")


def _norm_text(t: str) -> str:
    return re.sub(r"[\s,，]", "", t)


def extract_check_numbers(answer: str) -> List[str]:
    """答案里需要核对的「数字+单位」串（如 500元/晚、30个自然日、8-9折）。"""
    found = []
    for m in UNIT_NUM_RE.finditer(answer):
        tok = _norm_num(m.group(0))
        if tok and tok not in found:
            found.append(tok)
    return found


def verify_numbers(answer: str, source_text: str) -> List[str]:
    """返回答案中「原文找不到」的「数字+单位」串（空列表 = 全部通过）。

    规则：整串（含单位，如 3天 / 500元 / 8-9折）必须逐字出现在原文里，
    防止 500→1500 这类编造和 30个自然日→3天 这类单位改写。
    """
    src = _norm_text(source_text)
    bad = []
    for tok in extract_check_numbers(answer):
        if tok and tok not in src:
            bad.append(tok)
    return bad


@dataclass
class AnswerResult:
    answer: str = ""
    proactive_question: str = ""
    number_check: str = "passed"          # passed / repaired / failed / skipped
    flagged_numbers: List[str] = field(default_factory=list)
    used_ids: List[str] = field(default_factory=list)   # 模型实际引用的节点 id


class Answerer:
    def __init__(self, model=None, skill_instruction: str = "", timeout: float = 60.0,
                 system: str = "你是商旅知识专家，简洁回答。"):
        self.model = model
        self.skill_instruction = skill_instruction
        self.timeout = timeout
        self.system = system

    def build_context(self, docs: List[dict]) -> str:
        """docs: [{path, text, node_id}] → 【知识原文N】(id=…) 块。"""
        blocks = []
        for i, d in enumerate(docs, 1):
            nid = d.get("node_id", "")
            blocks.append(f"【知识原文{i}】(id={nid}) {d.get('path', '')}\n{d.get('text', '')}")
        return "\n\n".join(blocks)

    async def _call(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        if self.model is None:
            return None
        import asyncio
        try:
            resp = await asyncio.wait_for(
                self.model(as_messages([{"role": "system", "content": system or self.system}, {"role": "user", "content": prompt}])),
                timeout=self.timeout,
            )
            return extract_llm_text(resp, "")
        except asyncio.TimeoutError:
            logger.warning("答案生成超时（%.0fs）", self.timeout)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("答案生成失败：%s", exc)
            return None

    async def generate(self, query: str, docs: List[dict]) -> AnswerResult:
        context = self.build_context(docs)
        instruction = self.skill_instruction or "请基于知识库中的信息回答用户的问题。"
        prompt = f"""基于以下知识原文回答用户问题，简洁准确，不超过500字。

{instruction}

【问题】{query}

【知识原文】
{context}

【约束】
1. 只基于知识原文回答，没有就直接说"知识库中没有找到相关信息"
2. 金额、比例、天数、距离等数字必须与原文逐字一致，禁止换算或改写单位
3. 涉及城市档位时，先说明属于哪一档，再给标准
4. used 列出你实际据以回答的节点 id（1-3 个），不要列没用到的
5. 回答末尾不要编造来源

输出JSON：{{"answer": "...", "proactive_question": "..." 或 "", "used": ["节点id"]}}
"""
        raw = await self._call(prompt)
        if not raw:
            return AnswerResult(answer="", proactive_question="", number_check="skipped")
        answer, proactive, used = self._parse(raw)
        # 数字逐字校验
        source_all = "\n".join(d.get("text", "") for d in docs)
        bad = verify_numbers(answer, source_all)
        known_ids = {d.get("node_id") for d in docs if d.get("node_id")}
        result = AnswerResult(answer=answer, proactive_question=proactive,
                              used_ids=[u for u in used if u in known_ids])
        if not bad:
            result.number_check = "passed"
            return result
        # 修复一次：明确告知哪些数字没核对上
        repair_prompt = f"""你刚才的回答里有数字与知识原文不一致，请修正后重新输出。

【问题】{query}
【知识原文】
{context}

【你上一轮的回答】
{answer}

【未通过校验的数字】{ '、'.join(bad) }（这些必须逐字出自原文，或从回答中删除）
只输出JSON：{{"answer": "...", "proactive_question": "..." 或 ""}}
"""
        raw2 = await self._call(repair_prompt)
        if raw2:
            answer2, proactive2, used2 = self._parse(raw2)
            bad2 = verify_numbers(answer2, source_all)
            if answer2:
                result.answer = answer2
                if proactive2:
                    result.proactive_question = proactive2
                if used2:
                    result.used_ids = [u for u in used2 if u in known_ids]
                bad = bad2
        if bad:
            result.number_check = "failed"
            result.flagged_numbers = bad
            result.answer = result.answer.rstrip() + "\n\n（注：以上部分数字未能与引用条款逐字核对，请以原文为准）"
        else:
            result.number_check = "repaired"
        return result

    def _parse(self, raw: str) -> tuple:
        """返回 (answer, proactive_question, used_ids)。"""
        obj = extract_json_object(raw.strip())
        if obj:
            answer = obj.get("answer") or obj.get("response") or obj.get("content") or raw
            proactive = obj.get("proactive_question", "")
            if not isinstance(proactive, str):
                proactive = ""
            used = obj.get("used") or obj.get("used_ids") or []
            if not isinstance(used, list):
                used = []
            return answer.strip(), proactive.strip(), [str(u) for u in used if u]
        return raw.strip(), "", []