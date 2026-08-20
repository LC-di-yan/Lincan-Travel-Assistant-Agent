---
name: plan-trip
description: Use this skill when the user wants to plan a trip or asks for itinerary planning. Triggers when user says "规划行程", "安排路线", "我要去XX", "从XX到XX", or provides trip details like dates and destinations. This skill orchestrates IntentionAgent, EventCollectionAgent, and ItineraryPlanningAgent; all agents take model=model and are async.
---

# Plan Trip (行程规划)

为用户规划出行行程：意图识别 → 事项收集（出发地、目的地、日期等）→ 行程规划。所有 Agent 均使用 **model 对象**，且 **reply() 均为 async**。

## When to Use

- 用户说「规划行程」「从XX到XX」「X月X日去北京」等

## Agents（按顺序）

1. **IntentionAgent** — 识别意图与改写 query  
2. **EventCollectionAgent** — 提取出发地、目的地、日期、目的等  
3. **ItineraryPlanningAgent** — 生成行程（每日安排、交通、住宿建议等）

## 统一模型与异步

- 先创建 `OpenAIChatModel`（来自 `config.LLM_CONFIG`），再传给各 Agent 的 **model** 参数（本项目无 `model_config_name`）。
- 三个 Agent 的 `reply()` 都是 **async**，需 **await**。


## 行程规划 Prompt 指南

【核心原则】
1. **永远提供有价值的行程规划**，即使信息不完整
2. **不要因为缺少天气、交通等细节信息就拒绝规划**
3. **基于目的地和日期给出合理的景点推荐和行程安排**
4. 缺失的信息可以在注意事项中提醒用户补充，但不影响主体规划

【规划策略】
- 如果有目的地和日期：给出该地标志性景点的游览路线
- 如果缺少出发地：假设从目的地市内出发，规划市内一日游
- 如果缺少天气信息：根据当前季节给出建议（如冬季建议室内+室外结合）
- 如果缺少开放信息：推荐常规开放的景点，提醒提前确认

【行程规划要点】
1. 根据时间合理安排景点数量（一日游通常2-3个主要景点）
2. 考虑景点之间的交通时间和距离
3. 安排午餐、晚餐时间和推荐地点
4. 给出大致的时间安排（如9:00-12:00, 13:00-17:00等）
5. 提供交通方式建议（地铁、打车、步行等）

【任务】
基于已有信息生成实用的行程规划：
1. **必须给出具体的景点和活动安排**，不能只说"需要补充信息"
2. 在daily_plans中给出详细的时间表和景点
3. 在notes中补充注意事项和需要确认的信息
4. 在missing_info中列出建议用户补充的信息（但不影响规划）

【输出格式】(严格JSON)
{
    "itinerary": {
        "title": "北京3日游",
        "duration": "3天",
        "route": "北京 -> 北京",
        "daily_plans": [
            {
                "day": 1,
                "date": "2024-02-27",
                "city": "北京",
                "theme": "历史文化之旅",
                "activities": [
                    {
                        "time": "09:00-12:00",
                        "activity": "故宫博物院游览",
                        "location": "故宫博物院",
                        "description": "游览故宫，感受皇家建筑群的宏伟...",
                        "transport": "地铁1号线天安门东站"
                    }
                ],
                "meals": { "lunch": "...", "dinner": "..." }
            }
        ],
        "notes": ["建议提前7天预约故宫门票..."],
        "estimated_budget": "约2000元"
    },
    "planning_complete": true
}
