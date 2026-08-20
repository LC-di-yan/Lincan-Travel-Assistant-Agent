"""
偏好智能体
职责：收集用户的长期偏好
如"我的家在XXX"、"我喜欢XXX酒店"
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging

from utils.llm_response import extract_llm_json

logger = logging.getLogger(__name__)


class PreferenceAgent(AgentBase):
    """偏好智能体"""

    def __init__(self, name: str = "PreferenceAgent", model=None, memory_manager=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.memory_manager = memory_manager
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content={}, role="assistant")

        content = x.content if not isinstance(x, list) else x[-1].content

        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or str(data)
            except json.JSONDecodeError:
                user_query = content
        else:
            user_query = str(content)

        # 获取当前已保存的偏好
        current_preferences = {}
        if self.memory_manager:
            lt = self.memory_manager.long_term
            from context.long_term_memory import PostgresLongTermMemory
            if isinstance(lt, PostgresLongTermMemory):
                current_preferences = await lt.get_preference()
            else:
                current_preferences = lt.get_preference()

        current_prefs_str = json.dumps(current_preferences, ensure_ascii=False, indent=2)

        skill_instruction = self.skill_loader.get_skill_content("preference")
        if not skill_instruction:
            skill_instruction = "请分析用户的偏好。"

        prompt = f"""你是用户偏好分析专家，负责提取用户的长期偏好信息。

【当前已保存的用户偏好】
{current_prefs_str}

【新的用户输入】
{user_query}

【任务说明】
{skill_instruction}

输出JSON时额外包含"proactive_question"字段：
- 用"需要我帮你..."开头，基于用户偏好自然延伸一句反问，控制在25字内
- 如果用户说的是城市/目的地偏好（如"喜欢去青岛"），反问应涉及该地的行程、天气、交通等
- 如果不需要追问，设为空字符串""
- 示例："需要我帮你规划去青岛的出差行程吗？"

请直接输出JSON：
"""

        try:
            response = await self.model([{"role": "user", "content": prompt}])
            result = extract_llm_json(response, fallback={"has_preferences": False, "error": "parse_failed"})
        except Exception as e:
            logger.error(f"Preference collection failed: {e}")
            result = {"has_preferences": False, "error": str(e)}

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
