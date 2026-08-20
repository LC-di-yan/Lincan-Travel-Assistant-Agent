---
name: expense-tracker
description: Use this skill to record, query, and summarize travel expenses. Triggers when user says "记一笔打车费50元", "午餐花了80", "费用汇总", "花了多少钱", "报销统计". Does NOT handle general trip history queries ("差旅记录", "旅行记录"). Uses ExpenseTrackerAgent with LLM to parse natural language expense entries and query expense summaries.
---

## When to Use

- User wants to record a travel expense ("记一笔打车费50", "午餐80元", "酒店300一晚")
- User wants to query expenses ("这次出差花了多少钱", "费用汇总", "报销统计")
- User wants to delete/correct an expense ("删掉那笔打车费", "午餐改成60")

## Agent

- Class: `ExpenseTrackerAgent` at `skills/expense-tracker/script/agent.py`
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
