"""
费用记录智能体
职责：解析自然语言费用记录、查询汇总、删除费用
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
from datetime import date

from utils.llm_response import extract_llm_json

logger = logging.getLogger(__name__)


def _is_pg(memory_manager) -> bool:
    if memory_manager is None:
        return False
    from context.long_term_memory import PostgresLongTermMemory
    return isinstance(memory_manager.long_term, PostgresLongTermMemory)


class ExpenseTrackerAgent(AgentBase):
    """费用记录智能体"""

    def __init__(self, name: str = "ExpenseTrackerAgent", model=None, memory_manager=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.memory_manager = memory_manager
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({"error": "No input"}), role="assistant")

        content = x.content if not isinstance(x, list) else x[-1].content
        fast_expense = None
        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or str(data)
                fast_expense = data.get("fast_expense")
            except json.JSONDecodeError:
                user_query = content
        else:
            user_query = str(content)

        # 获取已有费用记录
        is_pg = _is_pg(self.memory_manager)
        existing_expenses = []
        if self.memory_manager:
            lt = self.memory_manager.long_term
            existing_expenses = await lt.get_expenses() if is_pg else lt.get_expenses()

        # 快速路径
        if fast_expense and fast_expense.get("amount"):
            result = {
                "action": "record",
                "expense": {
                    "category": fast_expense.get("category", "其他"),
                    "amount": fast_expense["amount"],
                    "currency": "CNY",
                    "description": fast_expense.get("description", ""),
                    "date": date.today().isoformat(),
                },
            }
            result = await self._execute_action(result, existing_expenses, is_pg)
            return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

        today = date.today().isoformat()
        expenses_str = json.dumps(existing_expenses[-20:], ensure_ascii=False, indent=2)

        skill_instruction = self.skill_loader.get_skill_content("expense-tracker")
        if not skill_instruction:
            skill_instruction = "请分析用户的费用记录请求。"

        prompt = f"""你是差旅费用管理专家，负责记录、查询和管理差旅费用。

【今天的日期】{today}

【最近的费用记录】
{expenses_str}

【用户输入】
{user_query}

【任务说明】
{skill_instruction}

请根据用户意图输出JSON：
- 记录费用：{{"action": "record", "expense": {{"category": "...", "amount": 数字, "currency": "CNY", "description": "...", "date": "YYYY-MM-DD"}}}}
- 查询汇总：{{"action": "query", "query_type": "total|by_category|by_date|summary"}}
- 删除费用：{{"action": "delete", "delete_index": 数字(从0开始)}}
- 如果无法理解：{{"action": "unknown", "answer": "无法理解您的请求"}}

分类参考：交通、餐饮、住宿、通讯、办公、娱乐、其他
请直接输出JSON，不要其他文字。
"""

        try:
            response = await self.model([{"role": "user", "content": prompt}])
            result = extract_llm_json(response)
        except Exception as e:
            logger.error(f"Expense parsing failed: {e}")
            result = {"action": "unknown", "answer": f"费用解析失败: {str(e)}"}

        result = await self._execute_action(result, existing_expenses, is_pg)

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    async def _execute_action(self, parsed: dict, existing: list, is_pg: bool) -> dict:
        """执行费用操作"""
        action = parsed.get("action", "unknown")

        if action == "record":
            return await self._record_expense(parsed, existing, is_pg)
        elif action == "query":
            result = self._query_expenses(parsed, existing)
            if existing:
                result["proactive_question"] = "需要我帮你导出这些费用明细用于报销吗？"
            return result
        elif action == "delete":
            result = await self._delete_expense(parsed, existing, is_pg)
            if result.get("action") != "error":
                result["proactive_question"] = "需要我帮你看看剩余的费用汇总吗？"
            return result
        else:
            return parsed

    async def _record_expense(self, parsed: dict, existing: list, is_pg: bool) -> dict:
        """记录一笔费用"""
        expense = parsed.get("expense", {})
        if not expense.get("amount"):
            return {"action": "error", "answer": "未识别到金额，请重新输入"}

        expense.setdefault("id", f"exp_{len(existing) + 1}")
        expense.setdefault("date", date.today().isoformat())
        expense.setdefault("currency", "CNY")
        expense.setdefault("category", "其他")

        if self.memory_manager:
            lt = self.memory_manager.long_term
            if is_pg:
                await lt.add_expense(expense)
            else:
                lt.add_expense(expense)

        amount = expense["amount"]
        category = expense["category"]
        desc = expense.get("description", "")
        total_after = sum(e.get("amount", 0) for e in existing) + amount

        return {
            "action": "record",
            "expense": expense,
            "total_after": total_after,
            "answer": f"已记录：{category} - {desc} ¥{amount:.2f}",
            "proactive_question": "需要我帮你看看这个月的费用汇总吗？",
        }

    def _query_expenses(self, parsed: dict, existing: list) -> dict:
        """查询费用汇总"""
        query_type = parsed.get("query_type", "summary")

        if not existing:
            return {
                "action": "query",
                "summary": {"total": 0, "count": 0, "by_category": {}, "items": []},
                "answer": "暂无费用记录"
            }

        total = sum(e.get("amount", 0) for e in existing)
        by_category = {}
        for e in existing:
            cat = e.get("category", "其他")
            by_category[cat] = by_category.get(cat, 0) + e.get("amount", 0)

        summary = {
            "total": total,
            "count": len(existing),
            "by_category": by_category,
            "items": existing[-10:]
        }

        if query_type == "total":
            answer = f"共{len(existing)}笔支出，合计 ¥{total:.2f}"
        elif query_type == "by_category":
            parts = [f"{cat}: ¥{amt:.2f}" for cat, amt in sorted(by_category.items(), key=lambda x: -x[1])]
            answer = "按类别：" + "，".join(parts)
        else:
            cat_lines = [f"  {cat}: ¥{amt:.2f}" for cat, amt in sorted(by_category.items(), key=lambda x: -x[1])]
            answer = f"本次差旅共{len(existing)}笔支出，合计¥{total:.2f}\n" + "\n".join(cat_lines)

        return {"action": "query", "summary": summary, "answer": answer}

    async def _delete_expense(self, parsed: dict, existing: list, is_pg: bool) -> dict:
        """删除一笔费用"""
        idx = parsed.get("delete_index", -1)
        if 0 <= idx < len(existing):
            deleted = existing[idx]
            if self.memory_manager:
                lt = self.memory_manager.long_term
                if is_pg:
                    await lt.delete_expense(idx)
                else:
                    lt.delete_expense(idx)
            return {
                "action": "delete",
                "deleted_id": deleted.get("id", ""),
                "answer": f"已删除：{deleted.get('category', '')} - {deleted.get('description', '')} ¥{deleted.get('amount', 0):.2f}"
            }
        return {"action": "error", "answer": "未找到该笔费用记录"}
