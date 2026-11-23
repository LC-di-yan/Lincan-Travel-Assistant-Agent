"""Parse and scope user-authorized ledger commands independently of the model."""

import hashlib
import re
import time
import uuid
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, timedelta

from utils.expenses import _CURRENCIES, _CURRENCY_PATTERN, _ISO_CODES, expense_fields, format_money, money

_CONFIRM = re.compile(r"确认费用\s+([a-f0-9]{24})")
_ADD_PREFIX = re.compile(r"^(?:请|帮我|给我|请帮我)?(?:记一笔|记几笔|记两笔|记录(?:一笔|以下|费用)|记账|登记(?:一笔|费用))\s*[:：,，]?\s*")
_ADD_SUFFIX = re.compile(r"[，,\s]*(?:请|帮我|请帮我)?(?:记一笔|记账|记到账本)[。！!]?\s*$")
_DELETE = re.compile(r"^(?:请|帮我|请帮我)?(?:删除|删掉|撤销)(?:费用)?\s*(.+)")
_EDIT = re.compile(r"^(?:请|帮我|请帮我)?(?:修改|更正)费用\s+([\w-]{1,32})\s*(?:改为|为|改成)\s*(.+)$")
_AMBIGUOUS = re.compile(r"[?？]|吗|是否|多少|有没|不用|不想|不要|别|没|先不|预算|预计|大概|大约|如果|假如|准备|计划|退款|退回|报价")
_OTHER_TASK = re.compile(r"规划|查票|天气|查询|顺便|同时|另外|并且|以及|还要|翻译|汇率|预订")
_DATE = re.compile(r"(?:(?:\d{4}[-年])?\d{1,2}[-月]\d{1,2})(?:日|号)?|前天|昨天|今天")
_AMOUNT = re.compile(r"\d+(?:\.\d{1,2})?")
_UNSUPPORTED_AMOUNT = re.compile(r"[-−–—负+]\s*\d|\d[.,，．]\d{3}|\d\s*[十百千万亿折%％]|[?？€£¥￥₩₹]|至少|不到|起步|左右|约|区间")
_READ = re.compile(r"(?:(?:请|帮我|我想|请帮我)?(?:查查|查询|查一下|查看|列出|统计|汇总|看一下|看下|看看)\s*.*(?:账单|支出|账本|账目|费用|花费)|(?:我)?(?:一共|总共|这个月|本月|今天|昨天|这次)?花了多少钱|(?:费用|账单|账本|支出|花费)(?:汇总|统计|明细|合计)|(?:报销统计|报销费用汇总))")
_CATEGORIES = {
    "交通": ("打车", "地铁", "公交", "机票", "火车票", "高铁", "停车", "加油"),
    "餐饮": ("餐", "饭", "早餐", "午餐", "晚餐", "吃"),
    "住宿": ("住宿", "酒店", "旅馆"),
    "通讯": ("通讯", "话费"),
    "办公": ("办公", "快递"),
    "娱乐": ("娱乐", "门票"),
}
_FILLER = re.compile(r"花了|付了|支付了|消费了|用了|一共")
_MAX_BATCH = 10
PROPOSAL_TTL = 600


@dataclass(frozen=True)
class ExpenseRequest:
    original: str
    session_id: str
    request_id: str


current_expense_request: ContextVar[ExpenseRequest | None] = ContextVar("current_expense_request", default=None)


@contextmanager
def expense_execution(original: str, session_id: str, request_id: str | None = None):
    token = current_expense_request.set(ExpenseRequest(original, session_id, request_id or uuid.uuid4().hex))
    try:
        yield
    finally:
        current_expense_request.reset(token)


def _parse_item(text, default_date=None):
    fields = expense_fields(text)
    if fields is None:
        return None
    raw = _DATE.sub("", text)
    if _UNSUPPORTED_AMOUNT.search(raw):
        return None
    amounts = list(_AMOUNT.finditer(raw))
    if len(amounts) != 1:
        return None
    matched = amounts[0]
    # A currency suffix belongs to the amount; other trailing text isn't guessed.
    tail = raw[matched.end():].strip()
    if tail and not re.fullmatch(r"[A-Za-z]{3}|[\u4e00-\u9fff]{1,6}", tail):
        return None
    if tail and (expense_fields(f"1{tail}") or {}).get("currency") != fields["currency"]:
        return None
    # If the suffix isn't a currency (e.g. '元到'), don't silently drop it.
    if tail and tail.upper() not in _ISO_CODES and tail.upper() != "RMB" and tail not in _CURRENCIES:
        return None
    try:
        amount = money(matched.group())
    except ValueError:
        return None
    if amount <= 0:
        return None
    label = _FILLER.sub("", raw[:matched.start()]).strip(" ：:元")
    if len(label) > 160:
        return None
    category = next((kind for kind, words in _CATEGORIES.items() if any(word in label for word in words)), "其他")
    return {"description": label, "category": category, "amount": float(amount), "currency": fields["currency"],
            "date": fields["date"] if _DATE.search(text) or not default_date else default_date}


def read_scope(text: str) -> dict | None:
    clean = text.strip().rstrip("。？?！!")
    if not _READ.fullmatch(clean) or re.search(r"删除|删掉|记账|记一笔|修改|不要|别查|预算|票价|酒店.*多少钱", clean):
        return None
    if re.search(r"酒店|机票|车票|打车", clean) and not re.search(r"我的|账|汇总|统计|本月|上月|报告|报销", clean):
        return None
    today = date.today()
    filters = {}
    if "本月" in clean or "这个月" in clean:
        filters = {"start": today.replace(day=1).isoformat(), "end": today.isoformat()}
    elif "昨天" in clean or "今天" in clean:
        day = (today - timedelta(days="昨天" in clean)).isoformat()
        filters = {"start": day, "end": day}
    elif re.search(r"上月|上个月|上周|本周|去年|这次|\d+月", clean):
        # Do not return an unfiltered total for a recognized but unhandled scope.
        return {"unsupported_scope": True}
    for kind in _CATEGORIES:
        if kind in clean:
            filters["category"] = kind
            break
    return filters


def parse_expense_command(text: str) -> dict | None:
    text = unicodedata.normalize("NFKC", text).strip().rstrip("。！!")
    confirm = _CONFIRM.fullmatch(text)
    if confirm:
        return {"kind": "confirm", "token": confirm[1]}
    if text.startswith("确认费用"):
        return {"kind": "invalid"}
    prefix, suffix = _ADD_PREFIX.match(text), _ADD_SUFFIX.search(text)
    edit, delete = _EDIT.fullmatch(text), _DELETE.fullmatch(text)
    if not (prefix or suffix or edit or delete):
        return None
    if _AMBIGUOUS.search(text) or _OTHER_TASK.search(text):
        return {"kind": "invalid"}
    if edit:
        item = _parse_item(edit[2])
        if item and not item["description"]:
            return {"kind": "update", "target": edit[1], "amount": item["amount"],
                    "currency": item["currency"] if _CURRENCY_PATTERN.search(edit[2]) else None}
        return {"kind": "invalid"}
    if delete:
        target = delete[1].strip()
        if re.search(r"所有|全部|批量|每一|最近[两二三四五\d]", target):
            return {"kind": "invalid"}
        return {"kind": "delete", "target": target}
    content = prefix.string[prefix.end():] if prefix else text[:suffix.start()]
    if _UNSUPPORTED_AMOUNT.search(_DATE.sub("", content)):
        return {"kind": "invalid"}
    parts = re.split(r"[、，,；;\n]|(?:\s*和\s*)(?=[\u4e00-\u9fff])", content)
    if len(parts) > _MAX_BATCH:
        return {"kind": "invalid"}
    items = []
    default_date = None
    for part in parts:
        part = part.strip()
        item = _parse_item(part, default_date) if part else None
        if item is None:
            return {"kind": "invalid"}
        if not items and _DATE.search(part):
            default_date = item["date"]
        items.append(item)
    return {"kind": "record", "items": items}


def mixed_expense_command(original: str) -> dict | None:
    """Only a separable, explicit ledger clause can survive a mixed request."""
    if re.search(r"不记|别记|不用记|不要|先不|如果|假如|退款|退回", original):
        return None
    parts = re.split(r"\s*[,，]?(?:顺便|另外|同时|并且|以及|并(?=记一笔|记账|记录)|[;；\n]+)\s*", original)
    if len(parts) < 2 or not any(_OTHER_TASK.search(part) or re.search(r"出差|查差旅记录|住宿推荐", part) for part in parts):
        return None
    candidates = [result for part in parts if (result := parse_expense_command(part))
                  and result["kind"] in {"record", "delete", "update"}]
    return candidates[0] if len(candidates) == 1 else None


def operation_token(request: ExpenseRequest) -> str:
    # The ledger itself is scoped by user; the token is additionally scoped by session.
    return hashlib.sha256(f"{request.session_id}:{request.request_id}".encode()).hexdigest()[:24]


def expense_snapshot(item: dict) -> dict:
    return {
        "id": item.get("id"), "amount": float(money(item.get("amount"))), "currency": item.get("currency") or "CNY",
        "description": item.get("description") or "", "category": item.get("category") or "其他",
        "date": str(item.get("date") or "") or None, "timestamp": str(item.get("timestamp") or ""),
    }


def prepare_expense_command(parsed: dict, ledger: list[dict]) -> dict | None:
    if parsed["kind"] == "record":
        return {"kind": "record", "items": parsed["items"]}
    target = parsed["target"]
    matches = [item for item in ledger if item.get("id") == target]
    if not matches and parsed["kind"] == "delete":
        if target in {"上一笔", "最近一笔", "最后一笔", "上一笔费用", "最近一笔费用", "最后一笔费用"}:
            matches = ledger[-1:]
        else:
            # An exact description is accepted only when it identifies one row.
            matches = [item for item in ledger if item.get("description") and item["description"] == target]
    if len(matches) != 1 or not matches[0].get("id"):
        return None
    snapshot = expense_snapshot(matches[0])
    if sum(item.get("id") == snapshot["id"] for item in ledger) != 1:
        return None
    command = {"kind": parsed["kind"], "expected": snapshot}
    if parsed["kind"] == "update":
        command["amount"] = parsed["amount"]
        command["currency"] = parsed["currency"] or snapshot["currency"]
    return command


def record_entries(command: dict, token: str) -> list[dict]:
    return [dict(item, id=f"exp_{token}_{i}") for i, item in enumerate(command["items"], 1)]


def operation_receipt(command: dict, token: str, totals: dict | None = None) -> dict:
    action = command["kind"]
    if action == "record":
        items = record_entries(command, token)
        reply = {"action": "record", "expenses": items, "expense": items[0]}
        if len(items) == 1:
            item = items[0]
            reply["answer"] = f"已记录：{item['description'] or item['category']} {format_money(item['amount'], item['currency'])}"
            if totals is not None:
                reply.update(total_after=totals[item["currency"]], total_currency=item["currency"])
        else:
            reply["answer"] = f"已一次性记录 {len(items)} 笔费用"
        if totals is not None:
            reply["totals_by_currency"] = totals
        return reply
    item = command["expected"]
    if action == "delete":
        return {"action": "delete", "deleted_id": item["id"],
                "answer": f"已删除：{item['description'] or item['category']} {format_money(item['amount'], item['currency'])}"}
    return {"action": "update", "expense": dict(item, amount=command["amount"], currency=command["currency"]),
            "answer": f"已修改费用 {item['id']}：{format_money(command['amount'], command['currency'])}"}


def stage_operation(current: dict | None, command: dict, now: int | None = None) -> dict:
    if current is not None:
        if current["command"]["request_hash"] != command["request_hash"]:
            return {"state": "conflict"}
        return operation_state(current, now)
    return {"state": "pending", "command": command, "expires_at": (int(time.time()) if now is None else now) + PROPOSAL_TTL}


def operation_state(current: dict | None, now: int | None = None) -> dict:
    if current is None:
        return {"state": "not_found"}
    if current["state"] != "pending":
        return current
    if current["expires_at"] <= (int(time.time()) if now is None else now):
        return {"state": "expired"}
    return current
