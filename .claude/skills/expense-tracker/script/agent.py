"""
费用记录智能体
职责：解析自然语言费用记录、查询汇总、删除费用
"""
from agents.base import SkillAgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import asyncio
import hashlib
import json
import logging
from utils.expenses import format_money, summarize_expenses

from utils.expense_commands import (
    current_expense_request, mixed_expense_command, operation_token, parse_expense_command, prepare_expense_command, read_scope,
)
from utils.as_compat import mk_msg, msg_text

logger = logging.getLogger(__name__)


def _is_pg(memory_manager) -> bool:
    if memory_manager is None:
        return False
    from context.long_term_memory import PostgresLongTermMemory
    return isinstance(memory_manager.long_term, PostgresLongTermMemory)


class ExpenseTrackerAgent(SkillAgentBase):
    """费用记录智能体"""

    def __init__(self, name: str = "ExpenseTrackerAgent", model=None, memory_manager=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.memory_manager = memory_manager
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if not x:
            return mk_msg(self.name, {"action": "error", "answer": "未收到费用请求"})
        request = current_expense_request.get()
        raw = msg_text(x[-1] if isinstance(x, list) else x)
        if request is None:
            # Standalone consumers may preview a draft but cannot authorize writes.
            try:
                data = json.loads(raw)
                raw = data.get("context", {}).get("rewritten_query", "") if isinstance(data, dict) else raw
            except json.JSONDecodeError:
                pass
        original = request.original if request else raw
        parsed = parse_expense_command(original)
        if request and (parsed is None or parsed["kind"] == "invalid"):
            parsed = mixed_expense_command(original) or parsed
        try:
            if parsed:
                result = await self._handle_command(request, parsed)
            elif (scope := read_scope(original)) is not None:
                if not self.memory_manager:
                    result = {"action": "error", "answer": "账本暂不可用"}
                elif scope.get("unsupported_scope"):
                    result = {"action": "error", "answer": "暂不支持这个查询范围，未返回全量合计"}
                else:
                    existing = await self._storage("get_expenses")
                    existing = [item for item in existing
                                if (not scope.get("category") or item.get("category") == scope["category"])
                                and (not scope.get("start") or scope["start"] <= (item.get("date") or "") <= scope["end"])]
                    result = self._query_expenses({}, existing)
            else:
                result = {"action": "error", "answer": "没有明确的账本操作，未修改账本。记账请说「记一笔打车50元」；查账请说「费用汇总」。"}
        except Exception as exc:
            logger.warning("Ledger operation failed (%s)", type(exc).__name__)
            result = {"action": "error", "answer": "账本操作暂不可用。若刚确认后中断，请重试同一个确认命令核对结果。"}
        return mk_msg(self.name, result)

    async def _storage(self, name, *args):
        method = getattr(self.memory_manager.long_term, name)
        if _is_pg(self.memory_manager):
            return await method(*args)
        return await asyncio.to_thread(method, *args)

    async def _handle_command(self, request, parsed):
        kind = parsed["kind"]
        if kind == "invalid":
            return {"action": "error", "answer": "费用操作有歧义或金额格式不明确，未修改账本。请分开说明每笔用途、正数金额和币种。"}
        if request is None:
            if kind == "record":
                return {"action": "preview", "expense": parsed["items"][0], "expenses": parsed["items"],
                        "answer": "仅预览，未写入。请在当前会话发起并确认。"}
            return {"action": "error", "answer": "请在当前会话发起费用操作，未修改账本。"}
        if not self.memory_manager:
            return {"action": "error", "answer": "账本暂不可用，未确认提交"}
        session_id = request.session_id
        if kind == "confirm":
            token = parsed["token"]
            result = await self._storage("expense_operation", session_id, token, "confirm")
        else:
            token = operation_token(request)
            request_hash = hashlib.sha256(request.original.encode()).hexdigest()
            if kind == "record":
                command = prepare_expense_command(parsed, [])
                result = await self._storage("expense_operation", session_id, token, "stage",
                                             {**command, "request_hash": request_hash})
            else:
                result = await self._storage("expense_operation", session_id, token, "lookup")
                if result["state"] == "not_found":
                    command = prepare_expense_command(parsed, await self._storage("get_expenses"))
                    if command is None:
                        return {"action": "error", "answer": "未能唯一定位这笔费用，未修改账本。请使用费用编号。"}
                    result = await self._storage("expense_operation", session_id, token, "stage",
                                                 {**command, "request_hash": request_hash})
                elif result.get("command", {}).get("request_hash", request_hash) != request_hash:
                    result = {"state": "conflict"}
        state = result["state"]
        if state == "committed":
            return result["receipt"]
        if state == "pending":
            return self._preview(result["command"], token)
        message = {
            "not_found": "当前会话未找到这项待确认操作，未修改账本。",
            "expired": "该确认已过期，未修改账本。请重新发起操作。",
            "conflict": "费用记录已变化或请求编号已被使用，未修改账本。请核对后重新发起。",
        }
        return {"action": "error", "answer": message.get(state, "未确认账本操作")}

    @staticmethod
    def _preview(command, token):
        kind = command["kind"]
        if kind == "record":
            items = command["items"]
            lines = [f"{item['date']} · {item['description'] or item['category']} · {format_money(item['amount'], item['currency'])}"
                     for item in items]
            detail = {"expenses": items, "expense": items[0]}
            heading = "将新增以下费用，尚未写入："
        else:
            item = command["expected"]
            previous = format_money(item["amount"], item["currency"])
            lines = [f"{item['id']} · {item['description'] or item['category']} · {previous}"]
            detail = {"expense": item}
            heading = "将删除以下费用，尚未修改账本：" if kind == "delete" else "将修改以下费用，尚未写入："
            if kind == "update":
                lines.append(f"新金额：{format_money(command['amount'], command['currency'])}")
        return {"action": "preview", "operation": kind, "answer": heading + "\n" + "\n".join(lines),
                "confirmation_command": f"确认费用 {token}", **detail}

    def _query_expenses(self, parsed: dict, existing: list) -> dict:
        """查询费用汇总"""
        query_type = parsed.get("query_type", "summary")

        if not existing:
            return {
                "action": "query",
                "summary": {"total": 0, "count": 0, "by_category": {}, "items": []},
                "answer": "暂无费用记录"
            }

        summary = summarize_expenses(existing)
        total = summary["total"]
        by_category = summary["by_category"]
        currency = summary["currency"]
        if currency is None:
            parts = [format_money(amount, code) for code, amount in sorted(summary["totals_by_currency"].items())]
            return {"action": "query", "summary": summary, "answer": "按原币种分别汇总：" + "；".join(parts) + "（未进行汇率换算）"}

        if query_type == "total":
            answer = f"共{len(existing)}笔支出，合计 {format_money(total, currency)}"
        elif query_type == "by_category":
            parts = [f"{cat}: {format_money(amt, currency)}" for cat, amt in sorted(by_category.items(), key=lambda x: -x[1])]
            answer = "按类别：" + "，".join(parts)
        else:
            cat_lines = [f"  {cat}: {format_money(amt, currency)}" for cat, amt in sorted(by_category.items(), key=lambda x: -x[1])]
            answer = f"共{len(existing)}笔支出，合计{format_money(total, currency)}\n" + "\n".join(cat_lines)

        return {"action": "query", "summary": summary, "answer": answer}
