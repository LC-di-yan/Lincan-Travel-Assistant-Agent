from inspect import isawaitable

import pytest

from context.long_term_memory import LongTermMemory
from server.personal.finance import LedgerProfile
from server.personal.models import AssignmentCommit, AssignmentPreview, ManualInput, ManualDraft
from server.personal.repository import JsonTrips
from server.personal.service import PersonalError, Trips


async def _maybe(result):
    return await result if isawaitable(result) else result


async def check_finance_contract(repo, book, other):
    trips = Trips(repo)
    service = LedgerProfile(repo)
    await _maybe(book.add_expense({"id": "personal_fee_chinese", "category": "交通", "amount": 120.25, "currency": "CNY", "date": "2026-11-11"}))
    await _maybe(book.add_expense({"id": "personal_fee_refund", "category": "交通", "amount": -20.25, "currency": "CNY", "date": "2026-11-12"}))
    await _maybe(book.add_expense({"id": "personal_fee_international", "category": "餐饮", "amount": 40, "currency": "USD", "date": "2026-10-12"}))
    before = await _maybe(book.get_expenses())
    limited = await service.report(limit=1)
    assert len(limited["items"]) == 1 and limited["count"] == 3 and limited["next_offset"] == 1
    assert limited["totals_by_currency"] == {"CNY": "100.00", "USD": "40.00"}
    assert limited["by_month"]["2026-11"] == {"CNY": "100.00"}
    plan = await trips.create(ManualInput(source="manual", draft=ManualDraft(title="交通测试")), "fee-trip-000000001")
    line = limited["items"][0]
    payload = AssignmentPreview(plan_id=plan["plan_id"], expected_entry_revision=line["revision"])
    with pytest.raises(PersonalError) as hidden:
        await LedgerProfile(other).preview(line["entry_ref"], payload)
    assert hidden.value.status == 404
    preview = await service.preview(line["entry_ref"], payload)
    assert preview["after_title"] == "交通测试" and preview["amount"] == "-20.25"
    assert not (await service.report(plan_id=plan["plan_id"]))["items"]
    command = AssignmentCommit(confirmed=True, operation_id=preview["operation_id"])
    once = await service.assign(line["entry_ref"], command, "fee-link-000000001")
    assert (await service.assign(line["entry_ref"], command, "fee-link-000000001")) == once
    assert (await service.report(plan_id=plan["plan_id"]))["totals_by_currency"] == {"CNY": "-20.25"}
    unassigned = await service.report(unassigned=True)
    assert unassigned["totals_by_currency"] == {"CNY": "120.25", "USD": "40.00"}
    after = await _maybe(book.get_expenses())
    baseline = lambda rows: [{k: v for k, v in item.items() if k not in ("trip_plan_id", "entry_ref")} for item in rows]
    assert baseline(before) == baseline(after)

    linked = (await service.report(plan_id=plan["plan_id"]))["items"][0]
    unlink = await service.preview(linked["entry_ref"], AssignmentPreview(plan_id=None, expected_entry_revision=linked["revision"]))
    updated = await service.assign(linked["entry_ref"], AssignmentCommit(confirmed=True, operation_id=unlink["operation_id"]),
                                   "fee-unlink-0000001")
    assert updated["trip_plan_id"] is None and (await service.report())["totals_by_currency"] == limited["totals_by_currency"]


async def test_finance_consistently_reads_the_existing_json_ledger(tmp_path):
    await check_finance_contract(JsonTrips("a", tmp_path), LongTermMemory("a", tmp_path), JsonTrips("b", tmp_path))


async def test_distinguishes_physically_separate_legacy_rows_with_duplicate_ids(tmp_path):
    book = LongTermMemory("a", tmp_path)
    entry = {"id": "duplicate", "category": "交通", "amount": 30, "currency": "CNY", "date": "2026-01-10",
             "timestamp": "2026-01-10T11:00"}
    book.add_expense(entry.copy())
    book.add_expense(entry.copy())
    repo = JsonTrips("a", tmp_path)
    service = LedgerProfile(repo)
    first = (await service.report())["items"]
    assert len({line["entry_ref"] for line in first}) == 2
    plan = await Trips(repo).create(ManualInput(source="manual", draft=ManualDraft(title="旧费用测试")), "fee-test-000000001")
    preview = await service.preview(first[0]["entry_ref"], AssignmentPreview(
        plan_id=plan["plan_id"], expected_entry_revision=first[0]["revision"],
    ))
    # A legacy edit still runs through the same file; deleting one picked
    # row must not link the remaining expense accidentally.
    owner_rows = book.get_expenses()
    index = next(i for i, line in enumerate(owner_rows) if line["entry_ref"] == first[0]["entry_ref"])
    assert book.delete_expense(index)
    book.add_expense({**entry, "amount": 35})
    with pytest.raises(PersonalError) as gone:
        await service.assign(first[0]["entry_ref"], AssignmentCommit(confirmed=True, operation_id=preview["operation_id"]),
                             "gone-assignment-001")
    assert gone.value.code == "expense_not_found"
    rows = (await service.report())["items"]
    assert len({line["entry_ref"] for line in rows}) == len(rows) == 2
    assert all(line["trip_plan_id"] is None for line in rows)
