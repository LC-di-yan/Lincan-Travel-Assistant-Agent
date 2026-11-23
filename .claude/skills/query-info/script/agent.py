"""
信息查询智能体 - 真实检索版
支持：天气（高德天气 API）、网络搜索（DDGS，开启 safesearch + 结果过滤）

使用 API：
- 天气：高德天气（需配置 AMAP_API_KEY；含今天在内共 4 日预报）
- 搜索：ddgs（Dux Distributed Global Search，可选 bing/duckduckgo 等，需安装：pip install ddgs）
"""
from agents.base import SkillAgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import asyncio
import json
import logging
import re
import time

from utils.llm_response import extract_llm_text
from utils.as_compat import mk_msg, msg_text, as_messages
from cache.decorators import cached
from utils.weather_intent import asks_about_clothing, needs_weather
from utils.local_transport import (
    TRANSPORT_ROUTE_QUESTION,
    TRANSPORT_TIME_QUESTION,
    local_transport_advice,
    needs_transport_advice,
)
from utils.weather_range import resolve_weather_range, shanghai_now
from utils.provider_http import amap_json
from utils.search_executor import SearchBusy, run_search, search_client

SEARCH_TIMEOUT = 8.0
SEARCH_BACKEND_TIMEOUT = 2

logger = logging.getLogger(__name__)

# 尝试导入 duckduckgo_search (旧包名) 或 ddgs (新包名)
try:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    logger.warning("ddgs not installed. Install with: pip install ddgs")

# 疑似垃圾/低质域名：多为 SEO 或不良站，不展示给用户
_SUSPICIOUS_DOMAIN_PATTERN = re.compile(
    r"\.(cc|tk|ml|ga|cf|gq|xyz|top|work|click|link|pw|buzz)(/|$)",
    re.I
)
# 域名主体若为长随机字母（无明显词），则过滤
_RANDOM_DOMAIN_PATTERN = re.compile(r"^[a-z0-9]{10,}$", re.I)

# 能力/身份类问题：直接给能力清单，不走网络搜索
_CAPABILITY_PATTERN = re.compile(
    r"你能(帮我)?做(什么|啥)|你会(什么|做啥|做什么)|能帮我做(什么|啥)|你有什么(功能|能力)|"
    r"怎么用(你|这个)|使用说明|你是谁|你是干什么的|能干什么"
)


def _is_suspicious_url(url: str) -> bool:
    """过滤疑似垃圾/不良站点（如部分 .cc/.tk 等易被滥用的域名）。"""
    if not url or not url.startswith("http"):
        return True
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc or ""
        # 去掉端口
        host = host.split(":")[0].lower()
        if not host:
            return True
        # 可疑 TLD
        if _SUSPICIOUS_DOMAIN_PATTERN.search(host):
            return True
        # 主域名部分（最后一个 . 之前若还有多段则取倒数第二段之前）
        parts = host.rsplit(".", 2)
        name = parts[0] if parts else ""
        if len(name) >= 10 and _RANDOM_DOMAIN_PATTERN.match(name):
            return True
        return False
    except Exception:
        return False


class InformationQueryAgent(SkillAgentBase):
    """
    信息查询智能体（真实检索版）

    核心功能：
    - 天气查询 - 使用高德天气 API（需配置 AMAP_API_KEY）
    - 网络搜索 - 使用 DDGS（开启 safesearch，过滤可疑来源）

    注意：
    - 差旅标准查询由独立的 RAGKnowledgeAgent 处理
    """

    def __init__(self, name: str = "InformationQueryAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    @cached("query_info_v2", ttl=900)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return mk_msg(self.name, {"query_success": False})

        # 解析输入（统一经 msg_text 取文本；content 恒为 str）
        content = msg_text(x) if not isinstance(x, list) else msg_text(x[-1])

        context = {}
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                context = data.get("context") or {}
                if not isinstance(context, dict):
                    context = {}
                user_query = context.get("rewritten_query", "") or data.get("query", "") or content
            else:
                user_query = content
        except json.JSONDecodeError:
            user_query = content

        # 追问只补已知上下文，不将缺失的城市默认成某座城市。
        if self._is_weather_query(user_query) and not self._extract_city_from_query(user_query):
            city = self._city_from_context(context)
            if city:
                user_query = f"{city} {user_query}"

        # 能力/身份类问题：直接作答，不要把整句话丢去做网络搜索
        # （原行为会把「你能帮我做什么」当搜索词，搜回无关站点）
        if _CAPABILITY_PATTERN.search(user_query or ""):
            logger.info("Capability query")
            result = {
                "query_type": "能力介绍",
                "query_success": True,
                "results": {
                    "summary": (
                        "我可以帮你做这些：\n"
                        "· 查天气、铁路余票和地图地点；在线搜索不是供应商报价\n"
                        "· 差旅标准、报销政策等知识库问答\n"
                        "· 行程规划、记账、汇率换算、翻译\n"
                        "直接说需求就行，比如「北京明天天气」「上海到北京的火车票」。"
                    ),
                    "sources": [],
                },
            }
            return mk_msg(self.name, result)

        if needs_transport_advice(user_query) and not self._is_weather_query(user_query):
            city = next((c for c in self._CITY_ADCODE_MAP if c in user_query), "")
            if not city:
                city = (context.get("key_entities") or {}).get("destination", "")
            result = {"query_type": "交通建议", "query_success": bool(city), "results": {"city": city, "summary": ""}}
            self._append_transport_advice(result, user_query)
            if not city:
                result["results"]["message"] = result["results"]["summary"]
            self._add_proactive_question(result, user_query)
            return mk_msg(self.name, result)

        # 天气类问题优先查 API，但不能提前丢弃同一请求中的交通需求。
        if self._is_weather_query(user_query):
            logger.info("Weather query")
            try:
                async with asyncio.timeout(11):
                    result = await self._weather_query(user_query)
                self._append_transport_advice(result, user_query)
                self._add_proactive_question(result, user_query)
                return mk_msg(self.name, result)
            except Exception as e:
                logger.warning("Amap weather query failed (%s)", type(e).__name__)
                requested = resolve_weather_range(user_query)
                # 普通搜索摘要无法保证日期与预报来源一致，不能拿今天的天气填充未来。
                if requested.explicit or not requested.include_current:
                    city = self._extract_city_from_query(user_query)
                    result = {
                        "query_type": "天气查询",
                        "query_success": False,
                        "results": {
                            "city": city,
                            "summary": f"暂未取得{city}{requested.label}的可靠预报，请稍后重试；不会使用其他日期的天气替代。",
                            "requested_range": requested.as_dict(),
                            "forecast": [],
                            "sources": [],
                        },
                    }
                    self._append_transport_advice(result, user_query)
                    return mk_msg(self.name, result)
                city = self._extract_city_from_query(user_query)
                search_query = f"{city} 天气" if city else user_query
                if asks_about_clothing(user_query):
                    search_query += " 穿衣建议"
                try:
                    result = await self._web_search(search_query)
                    result["query_type"] = "天气查询"
                    self._append_transport_advice(result, user_query)
                    self._add_proactive_question(result, user_query)
                    return mk_msg(self.name, result)
                except Exception as e2:
                    logger.warning("Weather search fallback failed (%s)", type(e2).__name__)
                    result = None
        else:
            result = None

        if result is None:
            logger.info("Web search query")
            try:
                result = await self._web_search(user_query)
                self._add_proactive_question(result, user_query)
            except Exception as e:
                logger.warning("Information query failed (%s)", type(e).__name__)
                result = {
                    "query_type": "网络搜索",
                    "query_success": False,
                    "results": {"message": "信息查询暂不可用，请稍后再试。"},
                }

        return mk_msg(self.name, result)

    def _append_transport_advice(self, result: Dict[str, Any], query: str) -> None:
        if not needs_transport_advice(query):
            return
        data = result.setdefault("results", {})
        cities = [city for city in self._CITY_ADCODE_MAP if city in query]
        city = data.get("city", "") or (cities[0] if len(cities) == 1 else "")
        if len(cities) > 1:
            guidance = {"summary": "问题涉及多个城市，请明确需要哪座城市的市内交通，还是城市之间的交通，以及具体起终点和出发时间；本次未计算城际路线。", "scope": "clarification", "sources": []}
        else:
            requested = resolve_weather_range(query)
            current = data.get("current") if requested.include_current else None
            guidance = local_transport_advice(city, query, current)
            if not requested.include_current and data.get("forecast"):
                weather_text = " ".join(day.get("weather", "") + " " + day.get("night_weather", "") for day in data["forecast"])
                if any(word in weather_text for word in ("雨", "雪", "沙", "雾")):
                    guidance["summary"] += "\n结合所查日期预报：部分时段可能有雨雪或能见度不佳，请减少露天候车，出发前再核对预警与运营信息。"
        data["transport_advice"] = guidance
        data["summary"] = "\n\n".join(x for x in (data.get("summary", ""), guidance["summary"]) if x)
        data.setdefault("sources", []).extend(guidance["sources"])

    def _add_proactive_question(self, result: Dict[str, Any], user_query: str) -> None:
        """根据查询类型和内容生成主动反问"""
        if not result.get("query_success"):
            return
        city = result.get("results", {}).get("city", "") or self._extract_city_from_query(user_query)
        if needs_transport_advice(user_query):
            if re.search(r"从.+(?:到|去|前往).+", user_query):
                result["proactive_question"] = TRANSPORT_TIME_QUESTION
            else:
                result["proactive_question"] = TRANSPORT_ROUTE_QUESTION
            return
        if result.get("query_type") == "天气查询" and city:
            result["proactive_question"] = f"需要我帮你查一下去{city}的交通方式和住宿吗？"
        elif result.get("query_type") == "网络搜索":
            result["proactive_question"] = "需要我帮你进一步了解相关信息吗？"

    def _is_weather_query(self, query: str) -> bool:
        """简单判断是否为天气类问题。"""
        q = (query or "").strip()
        if not q:
            return False
        return needs_weather(q)

    # 常见城市 → 高德 adcode 映射（避免地理编码 API 的编码问题）
    _CITY_ADCODE_MAP = {
        "北京": "110000", "上海": "310000", "广州": "440100", "深圳": "440300",
        "杭州": "330100", "南京": "320100", "成都": "510100", "武汉": "420100",
        "西安": "610100", "苏州": "320500", "天津": "120000", "重庆": "500000",
        "厦门": "350200", "青岛": "370200", "大连": "210200", "宁波": "330200",
        "无锡": "320200", "长沙": "430100", "郑州": "410100", "济南": "370100",
        "哈尔滨": "230100", "沈阳": "210100", "昆明": "530100", "合肥": "340100",
        "福州": "350100", "石家庄": "130100", "南昌": "360100", "贵阳": "520100",
        "太原": "140100", "南宁": "450100", "兰州": "620100", "海口": "460100",
        "呼和浩特": "150100", "乌鲁木齐": "650100", "拉萨": "540100", "银川": "640100",
        "西宁": "630100", "珠海": "440400", "东莞": "441900", "佛山": "440600",
        "温州": "330300", "无锡": "320200", "常州": "320400", "徐州": "320300",
        "烟台": "370600", "潍坊": "370700", "三亚": "460200", "桂林": "450300",
    }

    async def _weather_query(self, query: str) -> Dict[str, Any]:
        """
        使用高德天气 API 查询天气。
        流程：城市名 → adcode 映射 → 按查询日期请求实况/4日预报 → 结构化输出。
        任意一步失败则抛出异常，由调用方降级到网络搜索。
        """
        from datetime import timedelta

        city = self._extract_city_from_query(query)
        if not city:
            message = "想查询哪座城市的天气？请补充城市名称。"
            return {
                "query_type": "天气查询",
                "query_success": False,
                "results": {"message": message, "summary": message, "forecast": [], "sources": [], "needs_clarification": True},
            }

        requested = resolve_weather_range(query)
        if requested.error or requested.start > requested.today + timedelta(days=3) or requested.end < requested.today:
            return self._build_weather_result(city, {}, [], query=query)

        from config import AMAP_CONFIG

        api_key = AMAP_CONFIG.get("api_key", "")
        if not api_key:
            raise ValueError("AMAP_API_KEY 未配置")

        base_url = AMAP_CONFIG.get("base_url", "https://restapi.amap.com/v3")
        # 通过映射表获取 adcode
        adcode = self._CITY_ADCODE_MAP.get(city)
        city_name = city

        if not adcode:
            # 映射表没有则回退到地理编码 API
            geo_data = await amap_json(f"{base_url}/geocode/geo", {"key": api_key, "address": city, "output": "JSON"})
            geocodes = geo_data.get("geocodes", [])
            if not geocodes:
                return {
                    "query_type": "天气查询",
                    "query_success": False,
                    "results": {"message": f"未找到城市「{city}」，请检查城市名称"},
                }
            adcode = geocodes[0].get("adcode", "")
            city_name = geocodes[0].get("city", city) or city

        if not adcode:
            raise ValueError(f"城市「{city}」无 adcode")

        def fetch_weather(extension):
            return amap_json(f"{base_url}/weather/weatherInfo", {"key": api_key, "city": adcode, "extensions": extension})

        now = {}
        if requested.include_current:
            async with asyncio.TaskGroup() as group:
                current_task = group.create_task(fetch_weather("base"))
                forecast_task = group.create_task(fetch_weather("all"))
            now_data, forecast_data = current_task.result(), forecast_task.result()
            if now_data.get("status") != "1":
                raise ValueError(f"实时天气接口返回错误: {now_data.get('info')}")
            lives = now_data.get("lives", [])
            if not lives:
                raise ValueError("实时天气数据为空")
            now = lives[0]
        else:
            # 未来请求不依赖实时天气，也不把实况传递给穿衣、交通建议。
            forecast_data = await fetch_weather("all")
        if forecast_data.get("status") != "1":
            raise ValueError(f"天气预报接口返回错误: {forecast_data.get('info')}")
        forecasts = forecast_data.get("forecasts", [])
        casts = forecasts[0].get("casts", []) if forecasts else []

        # 构建结构化结果
        result = self._build_weather_result(city_name, now, casts, query=query)
        return result

    def _build_weather_result(
        self, city: str, now: Dict, casts: List[Dict], query: str = ""
    ) -> Dict[str, Any]:
        """仅展示请求日期内、且在高德可用时间窗内的真实数据。"""
        from datetime import date, timedelta

        now_time = shanghai_now()
        requested = resolve_weather_range(query, now=now_time)
        today = requested.today
        horizon_end = today + timedelta(days=3)
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        def day_label(day: date) -> str:
            relative = {0: "今天", 1: "明天", 2: "后天"}.get((day - today).days, "")
            return f"{relative} {day.month}/{day.day} {weekday_names[day.weekday()]}".strip()

        # 不能按 casts 的索引猜日期：API 可能缺日、乱序或返回旧预报。
        dated_casts = {}
        for cast in casts:
            try:
                cast_date = date.fromisoformat(str(cast.get("date", "")))
            except (ValueError, TypeError):
                continue
            if today <= cast_date <= horizon_end and requested.contains(cast_date):
                dated_casts[cast_date] = cast
        selected = sorted(dated_casts.items())
        forecast = []
        for cast_date, day in selected:
            low, high = day.get("nighttemp", "?"), day.get("daytemp", "?")
            forecast.append({
                "date": day_label(cast_date),
                "date_iso": cast_date.isoformat(),
                "weather": day.get("dayweather", "—"),
                "night_weather": day.get("nightweather", "—"),
                "temp_range": f"{low}~{high}°C",
                "description": self._brief_extra({"textDay": day.get("dayweather", ""), "tempMax": high}),
            })

        lines = [f"{city}天气【{requested.label}】", ""]
        current = None
        if requested.include_current and now:
            current_temp = now.get("temperature", "?")
            weather_text = now.get("weather", "—")
            wind_dir, wind_power = now.get("winddirection", ""), now.get("windpower", "")
            wind_info = f"{wind_dir}风 {wind_power}级".strip() if wind_dir else ""
            current = {
                "temp": current_temp,
                "weather": weather_text,
                "humidity": now.get("humidity", "?"),
                "wind": wind_info,
                "date_iso": today.isoformat(),
                "date": day_label(today),
                "observed_at": str(now.get("reporttime") or ""),
                "queried_at": now_time.isoformat(timespec="minutes"),
            }
            lines.extend([
                f"🌞当前实况（{today.isoformat()} {now_time:%H:%M}，北京时间）",
                f"{weather_text}，气温 {current_temp}℃",
                "，".join(part for part in (wind_info, f"湿度 {current['humidity']}%") if part),
                "",
            ])

        if selected:
            lines.append("🌡️今日全天预报" if len(selected) == 1 and selected[0][0] == today else "📅所查日期预报")
            for cast_date, day in selected:
                low, high = day.get("nighttemp", "?"), day.get("daytemp", "?")
                day_weather, night_weather = day.get("dayweather", "—"), day.get("nightweather", "—")
                extra = self._brief_extra({"textDay": day_weather, "tempMax": high})
                lines.append(f"{day_label(cast_date)}：白天{day_weather}，夜间{night_weather}，气温 {low}~{high}℃" + (f"；{extra}" if extra else ""))

        weather_notes = []
        advice = []
        requested_days = (requested.end - requested.start).days + 1
        missing = requested.error or len(selected) < requested_days
        if requested.error:
            lines.append(requested.error)
            weather_notes.append(requested.error)
        elif missing:
            lines.append("")
            lines.append(f"预报范围说明：高德仅提供含今天在内的 4 日预报（{today.isoformat()} 至 {horizon_end.isoformat()}）。")
            weather_notes.append(lines[-1])
            if requested.start < today or requested.end > horizon_end:
                lines.append("请求的部分或全部日期超出可用范围；仅列出已获取的所查日期，其余日期暂无可靠预报，不作推测。")
            else:
                lines.append("本次未获取到所查范围内全部日期的有效预报；缺失日期暂无可靠数据，不使用其他日期替代。")
            weather_notes.append(lines[-1])
        if not selected and not current and not requested.error:
            lines.append("暂未取得所查日期的可靠天气数据，请临近出行时再次查询。")
            weather_notes.append(lines[-1])

        # 当前实况只用于包含今天的请求；未来提醒逐日取自相应预报。
        if current:
            today_forecast = dated_casts.get(today, {})
            tips = self._generate_travel_tips(current["weather"], current["temp"], current["temp"], today_forecast.get("nightweather", ""), "", "", "")
            lines.extend(["", f"💡今日出行提醒：{tips}"])
            clothing = ""
            if asks_about_clothing(query):
                clothing = self._clothing_advice(current['temp'], today_forecast.get('nighttemp', '?'))
                lines.append(f"👕今日穿衣建议：{clothing}")
            advice.append({"date_iso": today.isoformat(), "date": day_label(today), "travel_tips": tips, "clothing_advice": clothing})
        for cast_date, day in selected:
            if cast_date == today and current:
                continue
            high, low = day.get("daytemp", "?"), day.get("nighttemp", "?")
            weather, night_weather = day.get("dayweather", ""), day.get("nightweather", "")
            tips = self._generate_travel_tips(weather, high, high, night_weather, "", "", "")
            if "雨" in weather or "雪" in weather:
                tips = "白天建议备伞，注意路面安全；" + tips
            lines.append(f"💡{day_label(cast_date)}出行提醒（基于预报）：{tips}")
            clothing = ""
            if asks_about_clothing(query):
                clothing = self._clothing_advice(high, low)
                lines.append(f"👕{day_label(cast_date)}穿衣建议（基于预报）：{clothing}")
            advice.append({"date_iso": cast_date.isoformat(), "date": day_label(cast_date), "travel_tips": tips, "clothing_advice": clothing})
        if asks_about_clothing(query) and not current and not selected:
            lines.append("👕穿衣建议：未取得所查日期的有效气温，暂不能可靠判断衣物厚度，请在预报可用后再确认。")
            weather_notes.append(lines[-1])

        data = {
            "presentation_version": 2,
            "summary": "\n".join(lines),
            "city": city,
            "forecast": forecast,
            "requested_range": requested.as_dict(),
            "forecast_limit": {"start_date": today.isoformat(), "end_date": horizon_end.isoformat()},
            "partial": bool(missing and (selected or current)),
            "advice": advice,
            "weather_notes": weather_notes,
            "sources": [{"title": "高德天气", "url": "https://www.amap.com"}],
        }
        if current:
            data["current"] = current
        if not selected and not current:
            data["message"] = data["summary"]
        return {
            "query_type": "天气查询",
            "query_success": bool((current or selected) and not requested.error),
            "results": data,
        }

    @staticmethod
    def _weather_emoji(text: str) -> str:
        """根据天气文字返回 emoji。"""
        if not text:
            return "🌤️"
        for keyword, emoji in [
            ("晴", "☀️"), ("多云", "⛅"), ("阴", "☁️"),
            ("雨", "🌧️"), ("雪", "❄️"), ("雾", "🌫️"),
            ("霾", "🌫️"), ("沙", "🏜️"), ("雷", "⛈️"),
        ]:
            if keyword in text:
                return emoji
        return "🌤️"

    @staticmethod
    def _uv_description(uv_index) -> str:
        """紫外线指数转中文描述。"""
        try:
            uv = int(uv_index)
        except (ValueError, TypeError):
            return ""
        if uv <= 2:
            return "弱"
        if uv <= 5:
            return "中等"
        if uv <= 7:
            return "较强"
        if uv <= 10:
            return "很强"
        return "极强"

    @staticmethod
    def _generate_day_description(text_day: str, temp_max: str, precip: str) -> str:
        """生成白天天气描述。"""
        parts = []
        try:
            t = int(temp_max)
            if t >= 35:
                parts.append("炎热闷热")
            elif t >= 30:
                parts.append("较热")
            elif t >= 20:
                parts.append("舒适")
            else:
                parts.append("偏凉")
        except (ValueError, TypeError):
            pass
        try:
            p = float(precip)
            if p > 0:
                parts.append(f"有降水（{p}mm）")
            else:
                parts.append("无降雨")
        except (ValueError, TypeError):
            pass
        if "晴" in text_day:
            parts.append("适合外出，注意防晒补水")
        return "，".join(parts) if parts else ""

    @staticmethod
    def _generate_night_description(text_night: str, precip: str) -> str:
        """生成夜间天气描述。"""
        parts = []
        try:
            p = float(precip)
            if p > 0:
                parts.append(f"有降水（{p}mm）")
        except (ValueError, TypeError):
            pass
        if "雨" in text_night or "雪" in text_night:
            parts.append(f"{text_night}，建议备伞")
        else:
            parts.append(text_night)
        return "，".join(parts) if parts else text_night

    @staticmethod
    def _brief_extra(day: Dict) -> str:
        """3日预报的简要附加信息。"""
        text_day = day.get("textDay", "")
        temp_max = day.get("tempMax", "")
        parts = []
        if "雨" in text_day or "雷" in text_day:
            parts.append("注意带伞")
        try:
            if int(temp_max) >= 35:
                parts.append("高温防暑")
        except (ValueError, TypeError):
            pass
        return "，".join(parts) if parts else ""

    @staticmethod
    def _generate_travel_tips(
        weather: str, temp: str, feels_like: str,
        night_weather: str, precip: str,
        uv_index: str, air_category: str,
    ) -> str:
        """根据天气数据生成出行提醒。"""
        tips = []
        try:
            fl = int(feels_like)
            if fl >= 35:
                tips.append("白天高温体感闷热，做好防暑")
            elif fl >= 30:
                tips.append("天气较热，注意防晒补水")
        except (ValueError, TypeError):
            pass

        if "雨" in night_weather or "雪" in night_weather:
            tips.append("晚间出门建议随身备伞，防范夜间阵雨")

        try:
            p = float(precip)
            if p > 5:
                tips.append("降水量较大，出行注意安全")
        except (ValueError, TypeError):
            pass

        try:
            uv = int(uv_index)
            if uv >= 8:
                tips.append("紫外线很强，务必做好防晒")
        except (ValueError, TypeError):
            pass

        if air_category and "污染" in air_category:
            tips.append("空气质量不佳，建议佩戴口罩")

        if not tips:
            if "晴" in weather:
                tips.append("天气不错，适合出行")
            else:
                tips.append("注意关注天气变化，合理安排出行")

        return "；".join(tips)

    @staticmethod
    def _clothing_advice(current_temp: str, low_temp: str) -> str:
        """仅根据已获取的气温提供粗略建议，不虚构实时天气。"""
        try:
            temp = float(current_temp)
            if not -90 <= temp <= 60:
                raise ValueError("invalid temperature")
        except (TypeError, ValueError):
            return "暂未取得有效气温，无法可靠判断衣物厚度，请核对所查日期的天气后选择。"
        if temp <= 5:
            advice = "建议穿羽绒服或厚外套，搭配保暖内搭和长裤，注意保暖"
        elif temp <= 15:
            advice = "建议穿外套、毛衣或长袖内搭和长裤"
        elif temp <= 22:
            advice = "建议穿长袖或薄外套，便于增减衣物"
        else:
            advice = "建议穿轻薄透气衣物，可选择短袖，注意防晒补水"
        try:
            low = float(low_temp)
            if -90 <= low <= 60 and temp - low >= 5:
                advice += "；早晚更凉，外出到夜间需额外备一件外套"
        except (TypeError, ValueError):
            pass
        return advice + "。建议仅供参考，请结合体感和户外活动时长调整。"

    def _city_from_context(self, context: Dict[str, Any]) -> str:
        """实体优先于会话焦点；只消费上游提供的城市，不猜测用户所在地。"""
        entities = context.get("key_entities") or {}
        focus = context.get("session_focus") or {}
        if not isinstance(entities, dict):
            entities = {}
        if not isinstance(focus, dict):
            focus = {}
        for candidate in (entities.get("destination"), focus.get("focus_city"), focus.get("last_search_city"), focus.get("current_trip_destination")):
            if isinstance(candidate, str):
                city = self._extract_city_from_query(candidate + "天气")
                if city:
                    return city
        return ""

    def _extract_city_from_query(self, query: str) -> str:
        """识别已知城市，或天气关键词前的明确地名；时间和指代词不是城市。"""
        q = re.sub(r"\s+", "", query or "")
        for city in sorted(self._CITY_ADCODE_MAP, key=len, reverse=True):
            if city in q:
                return city
        # 映射表以外的城市仍可交给地理编码，但不能把“未来”“明天天气”当地址。
        prefix = re.split(r"天气|气温|温度|冷不冷|热不热|穿什么|穿衣|交通", q, maxsplit=1)[0]
        prefix = re.sub(r"(?:\d{4}年)?\d{1,2}月\d{1,2}[日号]?|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[日号]", "", prefix)
        prefix = re.sub(r"(?:未来|接下来|往后|今后|随后)(?:的)?[\d零〇一二两三四五六七八九十百]+(?:个)?(?:天|日|周|星期)", "", prefix)
        prefix = re.sub(r"(?:下下|下|本|这)?(?:周|星期)(?:[一二三四五六日末]|天(?!气))?|大后天|后天|明天|明日|今天|今日|现在|当前|最近|未来|接下来", "", prefix)
        prefix = re.sub(r"^(?:(?:请|帮我|给我|为我|我想|想|我|问|查询|查一下|查查|查|看看|看一下|看|了解|一下|从|到|去|在|那|那么))+", "", prefix)
        prefix = re.sub(r"(?:的|起|开始|应该|怎么样|怎样|如何|呢|吧|啊|呀)+$", "", prefix)
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,10}", prefix) and not re.search(r"这里|那里|哪里|本地|当地|附近|全国|中国|国内|目的地|出差地|城市|同上|那边|这边|预报|情况|时间|天数|请|帮|推荐|查询|告诉|了解|麻烦|建议|需要|应该|衣服|的|我|你|大雨|小雨|暴雨|大雪|小雪|暴雪|晴天|阴天", prefix):
            return prefix.removesuffix("市")
        return ""

    async def _web_search(self, query: str) -> Dict[str, Any]:
        """
        网络搜索 - 使用 DDGS（Dux Distributed Global Search），开启 safesearch，过滤可疑来源。

        Args:
            query: 用户查询

        Returns:
            搜索结果
        """
        if not DDGS_AVAILABLE:
            return {
                "query_type": "网络搜索",
                "query_success": False,
                "results": {
                    "message": "搜索库未安装",
                    "note": "请运行：pip install ddgs",
                },
            }

        try:
            search_results = await run_search(lambda: self._search_sources(query), timeout=SEARCH_TIMEOUT)

            results = []
            for result in search_results:
                href = result.get("href", "")
                if _is_suspicious_url(href):
                    continue
                results.append({
                    "title": result.get("title", ""),
                    "snippet": result.get("body", ""),
                    "url": href,
                })
                if len(results) >= 5:
                    break

            if not results:
                return {
                    "query_type": "网络搜索",
                    "query_success": False,
                    "results": {"message": "未找到相关结果"},
                }

            # 使用 LLM 总结搜索结果
            summary = await self._summarize_search_results(query, results)
            if re.search(r"机票|航班|飞机|票价|余票|房价|可订", query):
                summary = "以下是网络搜索参考，未核验供应商票价、余票或房态。\n" + summary

            return {
                "query_type": "网络搜索",
                "query_success": True,
                "results": {
                    "summary": summary,
                    "sources": results,
                },
            }
        except (SearchBusy, TimeoutError) as exc:
            logger.info("Search delayed (%s)", type(exc).__name__)
            return {"query_type": "网络搜索", "query_success": False,
                    "results": {"message": "搜索服务繁忙或超时，请稍后再试。"}}
        except Exception as exc:
            logger.warning("Web search failed (%s)", type(exc).__name__)
            return {"query_type": "网络搜索", "query_success": False,
                    "results": {"message": "搜索服务暂不可用，请稍后再试。"}}

    @staticmethod
    def _search_sources(query):
        deadline = time.monotonic() + SEARCH_TIMEOUT
        ddgs = search_client(DDGS, SEARCH_BACKEND_TIMEOUT)
        had_response = False
        for backend in ("bing", "duckduckgo", "auto"):
            if time.monotonic() >= deadline:
                raise TimeoutError("search deadline exceeded")
            try:
                candidates = ddgs.text(query, max_results=10, safesearch="on", region="cn-zh", backend=backend)
            except Exception as exc:
                logger.debug("DDGS backend %s failed (%s)", backend, type(exc).__name__)
                continue
            had_response = True
            items = [item for item in candidates if not _is_suspicious_url(item.get("href", ""))]
            if items:
                return items
        if not had_response:
            raise RuntimeError("no search backend returned")
        return []

    async def _summarize_search_results(self, query: str, results: List[Dict]) -> str:
        """
        使用 LLM 总结搜索结果

        Args:
            query: 用户查询
            results: 搜索结果列表

        Returns:
            总结文本
        """
        if not results:
            return "未找到相关信息"

        # 构建搜索结果文本
        results_text = ""
        for i, result in enumerate(results, 1):
            results_text += f"\n{i}. {result['title']}\n{result['snippet']}\n"

        # 获取当前时间
        from datetime import datetime
        current_date = datetime.now().strftime("%Y年%m月%d日")
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

        # 动态读取 Prompt 指令 (Progressive Disclosure)
        skill_instruction = self.skill_loader.get_skill_content("query-info")
        if not skill_instruction:
            skill_instruction = "请直接回答用户的问题，保持简洁。"

        prompt = f"""根据以下搜索结果，简洁地回答用户的问题。

【当前时间】
{current_date} {weekday}
（用户查询中的相对时间请基于此日期理解，如"明天"、"2月28日"等）

【用户问题】
{query}

【搜索结果】
{results_text}

【任务说明】
{skill_instruction}
"""

        try:
            response = await self.model(as_messages([{"role": "user", "content": prompt}]))
            text = extract_llm_text(response, fallback="无法生成摘要")
            return text.strip() if text else "无法生成摘要"
        except Exception as e:
            logger.warning("Search summarization failed (%s)", type(e).__name__)
            return "搜索成功，但摘要生成失败"
