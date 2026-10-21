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
6. 额外输出"proactive_question"字段（字符串），用"需要我帮你..."开头，基于行程自然延伸一句反问（25字内），如不需要则设为""

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
            # 关闭「思考」：本任务按固定 schema 输出 JSON，思考 token 占输出量 30~50%，
            # 实测 2.7s → 0.9s；上游不支持该参数时自动回退。
            _msgs = [{"role": "user", "content": prompt}]
            try:
                response = await self.model(
                    _msgs, max_tokens=budget,
                    extra_body={"enable_thinking": False},
                )
            except Exception as _think_err:
                _es = str(_think_err)
                if "enable_thinking" in _es or "unexpected keyword" in _es:
                    logger.info("upstream rejected enable_thinking, falling back")
                    response = await self.model(_msgs, max_tokens=budget)
                else:
                    raise

            text = extract_llm_text(response)

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

            # 兜底：保证每个活动都有名称，避免前端回退成「未命名活动」
            _it = result.get("itinerary") or {}
            for _plan in (_it.get("daily_plans") or []):
                for _act in (_plan.get("activities") or []):
                    if not isinstance(_act, dict):
                        continue
                    _name = str(_act.get("activity") or "").strip()
                    if not _name or _name in {"未命名活动", "活动", "安排", "未命名"}:
                        _act["activity"] = (
                            str(_act.get("location") or "").strip()
                            or str(_act.get("description") or "").strip()[:12]
                            or "自由活动"
                        )

        except Exception as e:
            # 上游细节只进日志：403/401 的原始 JSON 一旦拼进 result["error"]，
            # 会经 assistant_summary 写进短期记忆、推给前端和 TTS 朗读。
            from utils.llm_errors import classify, describe, friendly

            logger.error("Itinerary planning failed: %s", describe(e))
            raw_text = locals().get('text', 'N/A')
            logger.error(f"Raw response text (first 500 chars): {str(raw_text)[:500]}")

            err_code = classify(e)
            if err_code == "parse" or "JSON" in str(e) or "parse" in str(e).lower():
                user_message = "抱歉，模型返回的数据格式有误，无法解析行程信息。请稍后重试或简化您的需求描述。"
            else:
                user_message = (
                    f"抱歉，行程暂时无法生成：{friendly(e)}。"
                    "系统已尝试自动切换备用模型，请稍后重试。"
                )

            result = {
                "itinerary": {
                    "title": "行程规划",
                    "duration": "待完善",
                    "daily_plans": []
                },
                "planning_complete": False,
                "error": user_message,
                "error_code": err_code,  # 前端/日志定位用，不含上游 URL、Key、JSON
            }

        # 返回JSON字符串格式
        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
