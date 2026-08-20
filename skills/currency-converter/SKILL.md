---
name: currency-converter
description: Use this skill for currency exchange rate queries and conversions. Triggers when user asks "100美元多少人民币", "日元汇率", "美元兑欧元", "汇率查询". Uses CurrencyConverterAgent to fetch real-time exchange rates from frankfurter.app API.
---

## When to Use

- User wants to convert between currencies ("100美元多少人民币", "5000日元换成人民币")
- User asks about exchange rates ("美元汇率", "日元兑人民币多少", "欧元汇率")

## Agent

- Class: `CurrencyConverterAgent` at `skills/currency-converter/script/agent.py`
- Constructor params: `name`, `model`
- `reply()` is async

## Initialization and Usage

```python
from skills.currency_converter.script.agent import CurrencyConverterAgent

agent = CurrencyConverterAgent(name="currency_converter", model=model)
response = await agent.reply(msg)
result = json.loads(response.content)
```

## Return Format

### Conversion Result
```json
{
  "action": "convert",
  "from": "USD",
  "to": "CNY",
  "amount": 100,
  "rate": 7.2456,
  "result": 724.56,
  "answer": "100 美元 = 724.56 人民币 (汇率: 1 USD = 7.2456 CNY)"
}
```

### Rate Query
```json
{
  "action": "rate",
  "from": "USD",
  "to": "CNY",
  "rate": 7.2456,
  "answer": "当前美元兑人民币汇率: 1 USD = 7.2456 CNY"
}
```

## Supported Currencies

CNY (人民币), USD (美元), EUR (欧元), JPY (日元), GBP (英镑), KRW (韩元), HKD (港币), TWD (新台币), SGD (新加坡元), THB (泰铢), AUD (澳元), CAD (加元)

## Parsing Rules

1. Extract source/target currencies from natural language
2. Extract amount if provided (default: 1 for rate queries)
3. Map common names: 美元→USD, 人民币/元→CNY, 日元→JPY, 欧元→EUR
4. If only one currency mentioned, pair with CNY as default

## API

Uses `frankfurter.app` (free, no key needed):
- Rate: `GET https://api.frankfurter.app/latest?from=USD&to=CNY`
- Historical: `GET https://api.frankfurter.app/2026-01-01?from=USD&to=CNY`
