"""
信息查询智能体 - 真实检索版
支持：天气（和风天气 QWeather API）、网络搜索（DDGS，开启 safesearch + 结果过滤）

使用 API：
- 天气：和风天气 QWeather（需 API Key，.env 中配置 QWEATHER_API_KEY）
- 搜索：ddgs（Dux Distributed Global Search，可选 bing/duckduckgo 等，需安装：pip install ddgs）
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import asyncio
import json
import logging
import re

from utils.llm_response import extract_llm_text
from cache.decorators import cached

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


class InformationQueryAgent(AgentBase):
    """
    信息查询智能体（真实检索版）

    核心功能：
    - 天气查询 - 使用和风天气 QWeather API（需配置 QWEATHER_API_KEY）
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

    @cached("query_info", ttl=900)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({"query_success": False}), role="assistant")

        # 解析输入
        content = x.content if not isinstance(x, list) else x[-1].content

        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or content
            except json.JSONDecodeError:
                user_query = content
        else:
            user_query = str(content)

        # 天气类问题优先走和风天气 API，失败则降级到网络搜索
        if self._is_weather_query(user_query):
            logger.info(f"Weather query: {user_query}")
            try:
                result = await self._weather_query(user_query)
                self._add_proactive_question(result, user_query)
                return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
            except Exception as e:
                logger.warning(f"QWeather failed, falling back to search: {e}")
                city = self._extract_city_from_query(user_query)
                search_query = f"{city} 天气" if city else user_query
                try:
                    result = await self._web_search(search_query)
                    result["query_type"] = "天气查询"
                    self._add_proactive_question(result, user_query)
                    return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
                except Exception as e2:
                    logger.warning(f"Weather search fallback also failed: {e2}")
                    result = None
        else:
            result = None

        if result is None:
            logger.info(f"Web search query: {user_query}")
            try:
                result = await self._web_search(user_query)
                self._add_proactive_question(result, user_query)
            except Exception as e:
                logger.error(f"Query failed: {e}")
                result = {
                    "query_type": "网络搜索",
                    "query_success": False,
                    "results": {"error": str(e)},
                }

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    def _add_proactive_question(self, result: Dict[str, Any], user_query: str) -> None:
        """根据查询类型和内容生成主动反问"""
        if not result.get("query_success"):
            return
        city = result.get("results", {}).get("city", "") or self._extract_city_from_query(user_query)
        if result.get("query_type") == "天气查询" and city:
            result["proactive_question"] = f"需要我帮你查一下去{city}的交通方式和住宿吗？"
        elif result.get("query_type") == "网络搜索":
            result["proactive_question"] = "需要我帮你进一步了解相关信息吗？"

    def _is_weather_query(self, query: str) -> bool:
        """简单判断是否为天气类问题。"""
        q = (query or "").strip()
        if not q:
            return False
        return "天气" in q or "气温" in q or "下雨" in q or "预报" in q

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
        流程：城市名 → adcode 映射 → 请求实时天气 + 4日预报 → 结构化输出。
        任意一步失败则抛出异常，由调用方降级到网络搜索。
        """
        from config import AMAP_CONFIG
        import subprocess

        api_key = AMAP_CONFIG.get("api_key", "")
        if not api_key:
            raise ValueError("AMAP_API_KEY 未配置")

        city = self._extract_city_from_query(query)
        if not city:
            return {
                "query_type": "天气查询",
                "query_success": False,
                "results": {"message": "未识别到城市，请说明具体城市，如：杭州下周的天气怎么样？"},
            }

        # 通过映射表获取 adcode
        adcode = self._CITY_ADCODE_MAP.get(city)
        city_name = city

        if not adcode:
            # 映射表没有则回退到地理编码 API
            from urllib.parse import quote
            base_url = AMAP_CONFIG.get("base_url", "https://restapi.amap.com/v3")
            geo_url = f"{base_url}/geocode/geo?key={api_key}&address={quote(city)}&output=JSON"
            result = subprocess.run(
                ["curl", "-s", "--compressed", geo_url],
                capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
            geo_data = json.loads(result.stdout)
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

        base_url = AMAP_CONFIG.get("base_url", "https://restapi.amap.com/v3")

        def _curl_get(url: str, params: dict) -> dict:
            query_str = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{url}?{query_str}"
            r = subprocess.run(
                ["curl", "-s", "--compressed", full_url],
                capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
            return json.loads(r.stdout)

        loop = asyncio.get_event_loop()

        # 并发请求实时天气 + 4日预报
        now_data, forecast_data = await asyncio.gather(
            loop.run_in_executor(None, _curl_get, f"{base_url}/weather/weatherInfo", {"key": api_key, "city": adcode, "extensions": "base"}),
            loop.run_in_executor(None, _curl_get, f"{base_url}/weather/weatherInfo", {"key": api_key, "city": adcode, "extensions": "all"}),
        )

        if now_data.get("status") != "1":
            raise ValueError(f"实时天气接口返回错误: {now_data.get('info')}")

        lives = now_data.get("lives", [])
        if not lives:
            raise ValueError("实时天气数据为空")

        now = lives[0]
        forecasts = forecast_data.get("forecasts", [])
        casts = forecasts[0].get("casts", [])[:4] if forecasts else []

        # 构建结构化结果
        result = self._build_weather_result(city_name, now, casts)
        return result

    def _build_weather_result(
        self, city: str, now: Dict, casts: List[Dict]
    ) -> Dict[str, Any]:
        """构建天气查询的结构化结果（高德天气数据格式）。"""
        from datetime import datetime

        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        now_time = datetime.now()
        time_str = now_time.strftime("%H:%M")
        date_str = f"{now_time.month} 月 {now_time.day} 日 {weekday_names[now_time.weekday()]}"

        # ── 当前天气字段（高德 lives 格式）──
        current_temp = now.get("temperature", "?")
        weather_text = now.get("weather", "—")
        humidity = now.get("humidity", "?")
        wind_dir = now.get("winddirection", "")
        wind_power = now.get("windpower", "")
        wind_info = f"{wind_dir}风 {wind_power}级".strip() if wind_dir else ""
        weather_emoji = self._weather_emoji(weather_text)

        # ── 今日预报（高德 casts 格式）──
        today = casts[0] if casts else {}
        today_temp_min = today.get("nighttemp", "?")
        today_temp_max = today.get("daytemp", "?")
        today_text_day = today.get("dayweather", "—")
        today_text_night = today.get("nightweather", "—")

        # ── 构建 summary ──
        lines = []

        # 标题行
        lines.append(f"{city}天气【{date_str}】")
        lines.append("")

        # 当前实况
        lines.append(f"🌞当前实况（{time_str}）")
        lines.append(f"{weather_text}，气温 {current_temp}℃")
        detail_parts = []
        if wind_info:
            detail_parts.append(wind_info)
        detail_parts.append(f"湿度 {humidity}%")
        lines.append("，".join(detail_parts))

        # 今日全天预报
        if today:
            lines.append("")
            lines.append("🌡️今日全天预报")
            lines.append(f"气温区间：{today_temp_min}℃ ~ {today_temp_max}℃")
            day_desc = self._generate_day_description(today_text_day, today_temp_max, "0")
            lines.append(f"白天：{today_text_day}，{day_desc}")
            lines.append(f"夜间：{today_text_night}")

        # 近几天简要预报
        if len(casts) >= 2:
            lines.append("")
            lines.append(f"📅近 {len(casts)} 天简要预报")
            for day in casts:
                fx_date = day.get("date", "")
                day_weather = day.get("dayweather", "—")
                temp_min = day.get("nighttemp", "?")
                temp_max = day.get("daytemp", "?")
                week_num = day.get("week", "")
                date_label = ""
                if fx_date:
                    try:
                        dt = datetime.strptime(fx_date, "%Y-%m-%d")
                        wd = weekday_names[dt.weekday()]
                        date_label = f"{dt.month}.{dt.day}（{wd}）"
                    except ValueError:
                        date_label = fx_date
                extra = self._brief_extra({"textDay": day_weather, "tempMax": temp_max})
                lines.append(f"{date_label}：{day_weather}，{temp_min}~{temp_max}℃{extra}")

        # 出行提醒
        lines.append("")
        tips = self._generate_travel_tips(weather_text, current_temp, current_temp, today_text_night, "0", "", "")
        lines.append(f"💡出行提醒：{tips}")

        summary = "\n".join(lines)

        # 构建结构化 forecast
        forecast = []
        for i, day in enumerate(casts):
            fx_date = day.get("date", "")
            day_weather = day.get("dayweather", "—")
            temp_min = day.get("nighttemp", "?")
            temp_max = day.get("daytemp", "?")
            date_label = ""
            if fx_date:
                try:
                    dt = datetime.strptime(fx_date, "%Y-%m-%d")
                    wd = weekday_names[dt.weekday()]
                    if i == 0:
                        date_label = f"今天 {wd}"
                    elif i == 1:
                        date_label = f"明天 {wd}"
                    elif i == 2:
                        date_label = f"后天 {wd}"
                    else:
                        date_label = f"{dt.month}/{dt.day} {wd}"
                except ValueError:
                    date_label = fx_date
            forecast.append({
                "date": date_label,
                "weather": day_weather,
                "temp_range": f"{temp_min}~{temp_max}°C",
            })

        return {
            "query_type": "天气查询",
            "query_success": True,
            "results": {
                "summary": summary,
                "city": city,
                "current": {
                    "temp": current_temp,
                    "weather": weather_text,
                    "humidity": humidity,
                    "wind": wind_info,
                },
                "forecast": forecast,
                "sources": [{"title": "高德天气", "url": "https://www.amap.com"}],
            },
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

    def _extract_city_from_query(self, query: str) -> str:
        """从问题中提取城市名（简单实现：常见城市列表匹配）。"""
        common_cities = [
            "北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州",
            "天津", "重庆", "厦门", "青岛", "大连", "宁波", "无锡", "长沙", "郑州", "济南",
            "哈尔滨", "沈阳", "昆明", "合肥", "福州", "石家庄", "南昌", "贵阳", "太原", "南宁",
        ]
        q = (query or "").strip()
        for city in common_cities:
            if city in q:
                return city
        # 否则取前 2～6 个连续中文字作为可能城市名
        m = re.search(r"[\u4e00-\u9fa5]{2,6}", q)
        return m.group(0).strip() if m else ""

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
            ddgs = DDGS()
            # 开启安全搜索，优先 bing 后端（质量更稳定），多取几条再过滤
            search_results = []
            for backend in ("bing", "duckduckgo", "auto"):
                try:
                    raw = ddgs.text(
                        query,
                        max_results=10,
                        safesearch="on",
                        region="cn-zh",
                        backend=backend,
                    )
                    search_results = list(raw)
                    if search_results:
                        break
                except Exception as e:
                    logger.debug(f"DDGS backend {backend} failed: {e}")
                    continue

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

            return {
                "query_type": "网络搜索",
                "query_success": True,
                "results": {
                    "summary": summary,
                    "sources": results,
                },
            }
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {
                "query_type": "网络搜索",
                "query_success": False,
                "results": {"error": f"搜索失败: {str(e)}"},
            }

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
            response = await self.model([{"role": "user", "content": prompt}])
            text = extract_llm_text(response, fallback="无法生成摘要")
            return text.strip() if text else "无法生成摘要"
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return "搜索成功，但摘要生成失败"
