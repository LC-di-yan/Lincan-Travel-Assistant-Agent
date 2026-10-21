---
name: place-search
description: Use this skill when the user wants to search for hotels, restaurants, or scenic spots in a city. Triggers when user asks "北京有哪些酒店", "帮我找成都的民宿", "XX有什么好吃的", "杭州有哪些景点". Uses PlaceSearchAgent to query Amap POI Search API (place/text). Requires AMAP_API_KEY configured in .env.
---

# Place Search (酒店/餐厅/景点搜索)

查询**酒店、民宿、餐厅、美食、景点、公园**等地点信息，使用高德 POI 搜索 API（`/v3/place/text`）。

## When to Use

- 酒店/住宿：「XX有哪些酒店」「推荐XX的民宿」「帮我找XX附近的宾馆」
- 餐厅/美食：「XX有什么好吃的」「XX火锅推荐」「XX附近吃饭的地方」
- 景点/游玩：「XX有哪些景点」「XX好玩的地方」「XX必去打卡」

## Agent

- **Class**: `PlaceSearchAgent` at `.claude/skills/place-search/script/agent.py`
- **Constructor params**: `name`, `model`
- **`reply()` is async**

## Initialization and Usage

```python
from skills.place_search.script.agent import PlaceSearchAgent

agent = PlaceSearchAgent(name="place_search", model=model)
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
