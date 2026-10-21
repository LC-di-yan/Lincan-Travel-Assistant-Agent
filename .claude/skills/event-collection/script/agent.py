"""
事项收集智能体
职责：收集用户的出发地/事项地点/事项时间/返程地

核心功能：
- 提取出发地、目的地、时间、返程地等基础信息
- 识别缺失信息并提示
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging

from config import SCENARIO_TOKENS
from utils.llm_response import extract_llm_json
from cache.decorators import cached

logger = logging.getLogger(__name__)

# 字段名 → 中文 映射（兜底翻译，即使 LLM 输出英文也能转为中文）
_FIELD_ZH_MAP = {
    "origin": "出发地",
    "destination": "目的地",
    "start_date": "出发日期",
    "end_date": "返程日期",
    "duration_days": "行程天数",
    "return_location": "返程地",
    "trip_purpose": "行程目的",
}


class EventCollectionAgent(AgentBase):
    """事项收集智能体"""

    def __init__(self, name: str = "EventCollectionAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model

    @cached("event_collection", ttl=1800)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content={}, role="assistant")

        # 解析输入内容
        content = x.content if not isinstance(x, list) else x[-1].content

        # 如果content是JSON字符串，解析它
        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or str(data)
                user_preferences = context.get("user_preferences", {})
            except json.JSONDecodeError:
                user_query = content
                user_preferences = {}
        else:
            user_query = str(content)
            user_preferences = {}

        # 构建用户背景信息
        background_info = ""
        if user_preferences:
            bg_parts = ["【用户背景信息】（可用于推断缺失信息）"]
            if user_preferences.get("home_location"):
                bg_parts.append(f"• 家庭住址: {user_preferences['home_location']}")
            if user_preferences.get("hotel_brands"):
                bg_parts.append(f"• 酒店偏好: {', '.join(user_preferences['hotel_brands'])}")
            if user_preferences.get("airlines"):
                bg_parts.append(f"• 航空偏好: {', '.join(user_preferences['airlines'])}")

            if len(bg_parts) > 1:
                background_info = "\n".join(bg_parts) + "\n\n"

        # 获取当前时间
        from datetime import datetime
        current_date = datetime.now().strftime("%Y年%m月%d日")
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

        prompt = f"""你是事项收集专家，负责提取旅行的基础信息。

【当前时间】
{current_date} {weekday}

{background_info}【用户输入】
{user_query}

【提取要求】
请尽可能提取以下信息：
1. origin - 出发地
2. destination - 目的地
3. start_date - 出发日期（YYYY-MM-DD格式）
4. end_date - 返程日期
5. duration_days - 行程天数
6. return_location - 返程地
7. trip_purpose - 行程目的
以上字段名引用对照（missing_info 中请使用中文名称）：
  origin → 出发地, destination → 目的地, start_date → 出发日期
  end_date → 返程日期, duration_days → 行程天数, return_location → 返程地
  trip_purpose → 行程目的

【日期处理规则】（重要）
- 当前时间是{current_date}
- 用户说"2月27日"或"2.27"等相对时间，请根据当前时间推断完整日期（年月日）
- 用户说"明天"、"后天"、"下周"等相对时间，请根据当前时间计算具体日期
- 所有日期必须输出完整的YYYY-MM-DD格式

【特殊处理】
- 对于"北京一日游"这类：destination和origin都设为北京
- 对于"一日游"：duration_days设为1
- 如果用户没说出发地，但有家庭住址信息，可推断出发地为家庭住址

【输出格式】(严格JSON)
{{
    "origin": "北京",
    "destination": "北京",
    "start_date": "2026-02-27",
    "end_date": "2026-02-27",
    "duration_days": 1,
    "return_location": "北京",
    "trip_purpose": "旅游",
    "missing_info": ["返程日期", "行程目的"],
    "extracted_count": 7,
    "summary": "北京一日游，2月27日"
}}

缺失的信息在missing_info中列出，missing_info中必须使用中文名称（如"出发地"而非"origin"），对应字段设为null。

额外输出"proactive_question"字段（字符串）：
- 用"需要我帮你..."开头，基于行程信息自然延伸一句反问（25字内）
- 例如：提取到"去上海出差" → "需要我帮你查一下上海的天气和住宿吗？"
- 如不需要则设为""
"""

        try:
            response = await self.model([{"role": "user", "content": prompt}], max_tokens=SCENARIO_TOKENS["event_collection"])
            result = extract_llm_json(response)
            # 兜底：将 missing_info 中的英文字段名转为中文
            if isinstance(result, dict) and "missing_info" in result:
                result["missing_info"] = [
                    _FIELD_ZH_MAP.get(item, item) for item in result["missing_info"]
                ]
        except Exception as e:
            logger.error(f"Event collection failed: {e}")
            result = {
                "missing_info": ["所有信息"],
                "extracted_count": 0,
                "error": str(e)
            }

        # 返回JSON字符串格式
        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
