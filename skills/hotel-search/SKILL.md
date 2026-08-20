---
name: hotel-search
description: Use this skill when the user wants to search for hotels, B&Bs, hostels, or other accommodation in a city. Triggers when user asks "北京有哪些酒店", "帮我找成都的民宿", "深圳五星级酒店", "XX附近的客栈". Uses HotelSearchAgent to query Amap POI Search API (place/text). Requires AMAP_API_KEY configured in .env.
---

# Hotel Search (酒店/民宿搜索)

查询**酒店、民宿、青年旅舍、宾馆**等住宿信息，使用高德 POI 搜索 API（`/v3/place/text`）。

## When to Use

- 用户问「XX有哪些酒店」「推荐XX的民宿」「帮我找XX附近的宾馆」
- 用户提到住宿需求且有具体城市

## Agent

- **Class**: `HotelSearchAgent` at `skills/hotel-search/script/agent.py`
- **Constructor params**: `name`, `model`
- **`reply()` is async**

## Initialization and Usage

```python
from skills.hotel_search.script.agent import HotelSearchAgent

agent = HotelSearchAgent(name="hotel_search", model=model)
response = await agent.reply(msg)
result = json.loads(response.content)
```

## Return Format

```json
{
  "query_type": "酒店搜索",
  "query_success": true,
  "results": {
    "city": "北京",
    "keyword": "酒店",
    "count": 230,
    "summary": "北京共有230家酒店，综合评分最高的是...",
    "hotels": [
      {
        "id": "B0FFGXXXXX",
        "name": "汉庭酒店(北京王府井店)",
        "address": "东城区王府井大街XX号",
        "rating": "4.6",
        "cost": "298-598",
        "tel": "010-XXXXXXXX",
        "photo": "https://...",
        "distance": "",
        "type": "酒店"
      }
    ],
    "sources": [{"title": "高德地图", "url": "https://www.amap.com"}]
  }
}
```

## API

Uses Amap POI Search API (requires `AMAP_API_KEY` in `.env`):
- Endpoint: `GET https://restapi.amap.com/v3/place/text`
- Params: `key`, `keywords`, `city`, `types`, `offset`, `page`, `extensions=all`, `citylimit=true`

### Accommodation Type Codes

| Code | Type |
|------|------|
| `060000` | 住宿服务 (大类) |
| `061000` | 酒店 |
| `061400` | 客栈/民宿 |

## Parsing Rules

1. Extract city from query (common city list + regex)
2. Extract accommodation type (酒店/民宿/青旅/宾馆 → types code)
3. Extract optional filters (brand name, star rating, price range)
4. Call Amap API with resolved parameters
5. Build structured result + LLM summary
