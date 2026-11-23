---
name: expense-tracker
description: "差旅账本：查询已记录费用、预览新增/修改/删除。示例：记一笔打车50元；费用汇总；删除上一笔费用。用户确认后才执行。价格咨询和一般行程历史不属于账本。"
---

## When to Use

- User explicitly requests recording one or more expenses ("记一笔打车费50元", "记两笔：打车50元、午餐80元")
- User wants to query expenses ("这次出差花了多少钱", "费用汇总", "报销统计")
- User wants to delete/correct an expense ("删除上一笔费用", "修改费用 exp_123 为 60元")

The execution layer parses the original user input without a model. A mutation
first returns `action: "preview"` and a session-scoped confirmation command.
Only the user sending that command commits the batch or targeted change.
Standalone `reply()` without a trusted request context never writes to the ledger.

## Agent

- Class: `ExpenseTrackerAgent` at `.claude/skills/expense-tracker/script/agent.py`
- Constructor params: `name`, `model`, `memory_manager`
- `reply()` is async

## Initialization and Usage

```python
from skills.expense_tracker.script.agent import ExpenseTrackerAgent

agent = ExpenseTrackerAgent(
    name="expense_tracker",
    model=model,
    memory_manager=memory_manager
)
response = await agent.reply(msg)
result = json.loads(response.content)
```

## Return Format

### Record Expense
```json
{
  "action": "record",
  "expense": {
    "id": "exp_1",
    "category": "交通",
    "amount": 50.0,
    "currency": "CNY",
    "description": "打车",
    "date": "2026-06-03"
  },
  "total_after": 50.0,
  "answer": "已记录：交通 - 打车 ¥50.00"
}
```

### Query Summary
```json
{
  "action": "query",
  "summary": {
    "total": 430.0,
    "count": 5,
    "by_category": {"交通": 150, "餐饮": 180, "住宿": 100},
    "items": [...]
  },
  "answer": "本次差旅共5笔支出，合计¥430.00"
}
```

### Delete Expense
```json
{
  "action": "delete",
  "deleted_id": "exp_3",
  "answer": "已删除：餐饮 - 午餐 ¥80.00"
}
```

## Expense Categories

- 交通 (taxi, subway, bus, train, flight, ride-hailing)
- 餐饮 (breakfast, lunch, dinner, snacks, coffee)
- 住宿 (hotel, accommodation)
- 通讯 (phone, internet, roaming)
- 办公 (printing, supplies, meeting room)
- 娱乐 (entertainment, sightseeing)
- 其他 (miscellaneous)

## Parsing Rules

1. Extract amount from natural language ("打车50" → amount=50, category=交通)
2. Infer category from keywords (打车/地铁/公交 → 交通, 午餐/晚餐/外卖 → 餐饮)
3. Default currency: CNY unless specified ("$100" → USD)
4. Default date: today unless specified ("昨天打车50" → yesterday's date)
5. Handle batch entries ("早餐15午餐25" → two separate expenses)

## Query Types

- Total: "一共花了多少", "总费用"
- By category: "交通花了多少", "餐饮费用"
- By date: "今天花了多少", "昨天的费用"
- Full summary: "费用汇总", "报销统计"
