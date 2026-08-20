"""
行程规划智能体
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import json
import logging

from config import SCENARIO_TOKENS
from utils.json_parser import robust_json_parse
from utils.llm_response import extract_llm_text
from cache.decorators import cached

logger = logging.getLogger(__name__)


class ItineraryPlanningAgent(AgentBase):
    """
    行程规划智能体（主协调）
    职责：协调事项收集、路线规划、酒店规划等多个子任务

    整合三层编排智能体的结果，生成完整行程计划
    """

    def __init__(self, name: str = "ItineraryPlanningAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    @cached("itinerary", ttl=3600)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content={}, role="assistant")

        # 解析输入内容
        content = x.content if not isinstance(x, list) else x[-1].content

        # 初始化变量
        user_query = ""
        context_info = {}
        previous_results = []
        user_preferences = {}

        # 如果content是JSON字符串，解析它（来自OrchestrationAgent）
        if isinstance(content, str):
            try:
                data = json.loads(content)
                context_info = data.get("context", {})
                user_query = context_info.get("rewritten_query", "")
                previous_results = data.get("previous_results", [])
                user_preferences = context_info.get("user_preferences", {})
            except json.JSONDecodeError:
                user_query = content
        elif isinstance(content, dict):
            context_info = content
            user_query = content.get("rewritten_query", str(content))
            user_preferences = content.get("user_preferences", {})

        # 整合所有可用信息
        all_info = {
            "user_query": user_query,
            "context": context_info,
        }

        # 从previous_results中提取其他agent的数据
        for prev in previous_results:
            agent_name = prev.get("agent_name", "")
            result_data = prev.get("result", {}).get("data", {})
            if result_data and agent_name:
                all_info[agent_name] = result_data

        # 回退：event_collection 合并到 intention 后，直接从 context 读取
        if "event_collection" not in all_info and context_info.get("event_collection"):
            all_info["event_collection"] = context_info["event_collection"]

        # 提取火车票信息
        train_ticket_info = ""
        if "train_ticket" in all_info:
            ticket_data = all_info["train_ticket"]
            if ticket_data.get("query_success"):
                trains = ticket_data.get("results", {}).get("trains", [])
                if trains:
                    train_ticket_info = "【火车票信息】\n"
                    for t in trains[:5]:  # 最多显示5趟
                        train_ticket_info += f"- {t['train_no']} ({t['train_type']}): {t['from_station']}→{t['to_station']} {t['depart_time']}-{t['arrive_time']} 历时{t['duration']} 二等座{t['second_class']} 一等座{t['first_class']}\n"
                    train_ticket_info += "\n请在攻略中推荐合适的火车班次，并标注出发/到达时间和票价参考。\n"

        # 构建用户偏好信息
        preferences_info = ""
        if user_preferences:
            pref_parts = ["【用户偏好】（规划时优先考虑）"]
            if user_preferences.get("home_location"):
                pref_parts.append(f"• 家庭住址: {user_preferences['home_location']}")
            if user_preferences.get("hotel_brands"):
                pref_parts.append(f"• 酒店偏好: {', '.join(user_preferences['hotel_brands'])}")
            if user_preferences.get("airlines"):
                pref_parts.append(f"• 航空偏好: {', '.join(user_preferences['airlines'])}")
            if user_preferences.get("seat_preference"):
                pref_parts.append(f"• 座位偏好: {user_preferences['seat_preference']}")

            if len(pref_parts) > 1:
                preferences_info = "\n".join(pref_parts) + "\n\n"

        # 获取当前时间
        from datetime import datetime
        current_date = datetime.now().strftime("%Y年%m月%d日")
        current_month = datetime.now().month
        current_season = "冬季" if current_month in [12, 1, 2] else \
                        "春季" if current_month in [3, 4, 5] else \
                        "夏季" if current_month in [6, 7, 8] else "秋季"
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

        # 尝试从 SKILL.md 动态读取详细指令 (Progressive Disclosure)
        skill_instruction = self.skill_loader.get_skill_content("plan-trip")
        if not skill_instruction:
            # Fallback: 如果读取失败，使用默认的简单指令
            skill_instruction = "请根据用户需求和偏好生成行程规划。"

        # 避免重复：train_ticket 原始数据已在 train_ticket_info 中格式化展示
        prompt_info = dict(all_info)
        prompt_info.pop("train_ticket", None)

        prompt = f"""你是行程规划专家。根据以下信息生成行程。

【当前时间】{current_date} {weekday}
【需求】{user_query}
{preferences_info}{train_ticket_info}【信息】
{json.dumps(prompt_info, ensure_ascii=False, indent=2)}

【指南】{skill_instruction}

【输出要求】（严格遵守）
1. 每日最多3个活动，每个描述不超过80字
2. 总行程不超过5天
3. 所有字符串值必须用英文双引号包围，内部引号用 \" 转义
4. 不要在字符串值中使用换行符
5. 确保JSON格式完整，可直接被解析
6. 每个 activity 对象必须包含 "activity" 字段：一个简短的活动名称（3-8个字，如"故宫博物院游览"、"高铁前往北京"、"八达岭长城登城"），直接概括该时间段的核心活动
7. 额外输出"proactive_question"字段（字符串），用"需要我帮你..."开头，基于行程自然延伸一句反问（25字内），如不需要则设为""

直接输出JSON：
"""

        try:
            # 按行程复杂度选择 token 预算
            event_data = all_info.get("event_collection", {})
            duration = event_data.get("duration_days") or context_info.get("duration_days")
            if duration and duration > 1:
                budget = SCENARIO_TOKENS["itinerary_complex"]
            else:
                budget = SCENARIO_TOKENS["itinerary"]

            # 调用模型 - 使用消息列表格式
            # 推理模型（deepseek-v4-flash）会先输出 thinking 块再输出 text 块，
            # 且 thinking 与 text 共享 max_tokens 预算。若预算不足，thinking 会占满
            # 预算导致最终 text 为空。因此这里在拿到空响应时自动加大预算重试。
            text = ""
            attempt_budget = budget
            for _attempt in range(2):
                response = await self.model(
                    [{"role": "user", "content": prompt}],
                    max_tokens=attempt_budget,
                )
                text = extract_llm_text(response)
                if text and text.strip():
                    break
                logger.warning(
                    "Itinerary LLM returned empty text at max_tokens=%s "
                    "(reasoning likely exhausted the budget); retrying with a larger budget",
                    attempt_budget,
                )
                attempt_budget = min(attempt_budget * 2, 32768)

            # 解析结果
            result = None
            
            # 策略1: 尝试标准解析 (依赖 robust_json_parse 的清洗能力)
            try:
                result = robust_json_parse(text, fallback=None)
            except Exception:
                # 策略2: 使用 raw_decode 解析前缀 JSON (最强力，能忽略尾随文本如 Thinking)
                try:
                    # 再次清理 Markdown (以防 extract_json_from_async_response 漏网)
                    clean_text = text
                    if "```" in clean_text:
                        import re
                        clean_text = re.sub(r'```json\s*', '', clean_text, flags=re.IGNORECASE)
                        clean_text = re.sub(r'```', '', clean_text)
                    
                    clean_text = clean_text.strip()
                    start_idx = clean_text.find('{')
                    
                    if start_idx != -1:
                        # 从第一个 { 开始尝试解析
                        clean_text = clean_text[start_idx:]
                        decoder = json.JSONDecoder()
                        obj, _ = decoder.raw_decode(clean_text)
                        result = obj
                    else:
                        raise ValueError("No JSON object start '{' found")
                except Exception as decode_err:
                    # 如果策略2也失败，抛出包含详细信息的异常
                    raise ValueError(f"All JSON parsing attempts failed. Strategy 2 error: {decode_err}")

            if result is None:
                raise ValueError("Parsed result is None")

        except Exception as e:
            logger.error(f"Itinerary planning failed: {e}")
            # Ensure text is defined for logging even if extraction failed
            # 使用 locals().get 安全获取 text，防止 UnboundLocalError
            raw_text = locals().get('text', 'N/A')
            logger.error(f"Raw response text (first 500 chars): {str(raw_text)[:500]}")

            # 构建用户友好的错误消息
            error_detail = str(e)
            if "JSON" in error_detail or "parse" in error_detail.lower():
                user_message = "抱歉，模型返回的数据格式有误，无法解析行程信息。请稍后重试或简化您的需求描述。"
            else:
                user_message = f"行程规划过程中出现问题：{error_detail}"

            result = {
                "itinerary": {
                    "title": "行程规划",
                    "duration": "待完善",
                    "daily_plans": []
                },
                "planning_complete": False,
                "error": user_message,
                "technical_error": str(e)  # 保留技术细节用于调试
            }

        # 返回JSON字符串格式
        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
