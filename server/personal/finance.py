"""旧账本的行程归属和分币种统计；任何操作都不新增消费。"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from server.personal.service import PersonalError, _idempotent, _now, _plan, _prune_operations, _slug_payload
from utils.expenses import currency_code, money


def _date(value):
    if value:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            pass
    return None


def _legacy_fingerprint(row):
    data = [str(row.get(field) or "") for field in ("id", "category", "amount", "currency", "description", "date", "timestamp")]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def _ids(rows, owner, materialize=False):
    seen = defaultdict(int)
    reserved = {str(row["entry_ref"]) for row in rows if isinstance(row, dict) and row.get("entry_ref")}
    for row in rows:
        if not isinstance(row, dict):
            yield None, None
            continue
        ref = row.get("entry_ref")
        if row.get("row_id") is None and not ref:
            fingerprint = _legacy_fingerprint(row)
            while not ref or ref in reserved:
                order = seen[fingerprint]
                seen[fingerprint] += 1
                ref = str(uuid5(NAMESPACE_URL, f"aligo:expense:{owner}:{fingerprint}:{order}"))
            reserved.add(ref)
            if materialize:
                row["entry_ref"] = ref
        yield str(ref), row


def _item(ref, row):
    category = str(row.get("category") or "其他")[:32]
    amount = f'{money(row.get("amount")):.2f}'
    currency = currency_code(row.get("currency"))
    day = _date(row.get("date"))
    plan = str(row["trip_plan_id"]) if row.get("trip_plan_id") else None
    return {"entry_ref": ref, "trip_plan_id": plan, "amount": amount, "currency": currency, "category": category,
            "description": str(row.get("description") or "")[:300],
            "date": day.isoformat() if day else None, "timestamp": str(row.get("timestamp") or ""),
            "revision": _slug_payload(ref, _legacy_fingerprint(row), plan)}


def _require_entry(ref, data, owner, materialize=False):
    for key, row in _ids(data.expenses, owner, materialize):
        if key == ref:
            try:
                return row, _item(key, row)
            except ValueError:
                raise PersonalError(422, "invalid_ledger_entry", "该旧费用金额或币种无效，请先修正原账本。") from None
    raise PersonalError(404, "expense_not_found", "找不到该费用，请刷新原账本后再试。")


def _amounts(items, selector):
    sums = defaultdict(lambda: defaultdict(Decimal))
    for item in items:
        key = selector(item)
        if key is not None:
            sums[key][item["currency"]] += Decimal(item["amount"])
    return {key: {currency: f"{subtotal:.2f}" for currency, subtotal in currencies.items()}
            for key, currencies in sorted(sums.items())}


class LedgerProfile:
    def __init__(self, repository):
        self.repository = repository
        self.owner = repository.user_id

    async def report(self, *, plan_id=None, unassigned=False, start_date=None, end_date=None, offset=0, limit=50):
        key = str(plan_id) if plan_id else None

        def read(data):
            if key:
                _plan(data, key)
            valid = []
            invalid, without_date = 0, 0
            for ref, row in _ids(data.expenses, self.owner):
                linked = str(row["trip_plan_id"]) if row and row.get("trip_plan_id") else None
                if (key or unassigned) and linked != key:
                    continue
                try:
                    item = _item(ref, row)
                except (AttributeError, TypeError, ValueError):
                    invalid += 1
                    continue
                if not item["date"]:
                    without_date += 1
                if start_date or end_date:
                    day = _date(item["date"])
                    if day is None or start_date and day < start_date or end_date and day > end_date:
                        continue
                valid.append(item)
            valid.sort(key=lambda item: (item["date"] or "", item["timestamp"], item["entry_ref"]), reverse=True)
            return {"items": valid[offset:offset + limit], "count": len(valid),
                    "next_offset": offset + limit if len(valid) > offset + limit else None,
                    "totals_by_currency": _amounts(valid, lambda _: "total").get("total", {}),
                    "by_category": _amounts(valid, lambda item: item["category"]),
                    "by_month": _amounts(valid, lambda item: item["date"][:7] if item["date"] else None),
                    "by_year": _amounts(valid, lambda item: item["date"][:4] if item["date"] else None),
                    "invalid_count": invalid, "unknown_date_count": without_date}
        return await self.repository.run(read, ledger=True)

    async def preview(self, entry_ref, payload):
        entry_ref = str(entry_ref)

        def apply(data):
            _, before = _require_entry(entry_ref, data, self.owner, materialize=True)
            if before["revision"] != payload.expected_entry_revision:
                raise PersonalError(412, "expense_changed", "费用已变更，请刷新后重新关联。")
            target = _plan(data, str(payload.plan_id)) if payload.plan_id else None
            if target and target["lifecycle"] in {"archived", "superseded", "cancelled"}:
                raise PersonalError(409, "invalid_expense_target", "费用不能新关联至已归档、取消或被替换的行程。")
            if before["trip_plan_id"] == (target and target["plan_id"]):
                raise PersonalError(409, "same_assignment", "这笔费用的归属没有变化。")
            now = _now()
            _prune_operations(data, now)
            if len(data.operations) >= 800:
                raise PersonalError(429, "too_many_operations", "操作过于频繁，请稍后再试。")
            op_id = uuid4().hex
            expires = (now + timedelta(minutes=10)).isoformat()
            previous = data.plans.get(before["trip_plan_id"], {})
            operation = {"entry_ref": entry_ref, "expected_entry_revision": before["revision"],
                         "target": target and target["plan_id"], "target_revision": target and target["revision"],
                         "expires_at": expires, "used": False}
            data.operations[f"expense_preview:{op_id}"] = operation
            return {"operation_id": str(UUID(op_id)), "expires_at": expires, "amount": before["amount"],
                    "currency": before["currency"], "before_title": previous.get("title"), "after_title": target and target["title"]}

        return await self.repository.run(apply, write=True, ledger=True, expense_ref=entry_ref)

    async def assign(self, entry_ref, payload, idempotency_key):
        entry_ref = str(entry_ref)
        fingerprint = _slug_payload(entry_ref, str(payload.operation_id), payload.confirmed)

        def write(data):
            def apply():
                op_key = f"expense_preview:{payload.operation_id.hex}"
                operation = data.operations.get(op_key)
                if not operation or operation["entry_ref"] != entry_ref:
                    raise PersonalError(410, "preview_expired", "关联预检已过期，请重新预检。")
                if operation["used"]:
                    raise PersonalError(409, "preview_used", "这次费用关联已经确认。")
                row, before = _require_entry(entry_ref, data, self.owner, materialize=True)
                if before["revision"] != operation["expected_entry_revision"]:
                    raise PersonalError(412, "expense_changed", "费用或归属已变更，请重新预检。")
                target = _plan(data, operation["target"]) if operation["target"] else None
                if target and target["revision"] != operation["target_revision"]:
                    raise PersonalError(409, "assignment_target_changed", "目标行程已变更，请重新预检。")
                row["trip_plan_id"] = target["plan_id"] if target else None
                operation["used"] = True
                return {"entry_ref": entry_ref, "trip_plan_id": row["trip_plan_id"]}
            return _idempotent(data, "expense_commit", idempotency_key, fingerprint, apply)
        return await self.repository.run(write, write=True, ledger=True, expense_ref=entry_ref)
