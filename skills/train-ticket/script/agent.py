"""
火车票查询智能体
职责：查询12306火车票信息，包括余票、票价、经停站、中转换乘

核心功能：
- 查余票：指定日期、区间的列车余票
- 查票价：特定车次的票价
- 搜车站：根据关键词搜索车站
- 经停站：列车经过的所有站点
- 中转换乘：两地之间的换乘方案
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import json
import logging
import re
import time
import os
from datetime import datetime, timedelta

from cache.decorators import cached

logger = logging.getLogger(__name__)

# 站点编码缓存
_stations_cache = None
_stations_cache_time = 0
STATIONS_CACHE_TTL = 86400  # 24小时

# 查询结果缓存
_query_cache = {}
QUERY_CACHE_TTL = 600  # 10分钟


def _load_stations() -> Dict[str, Dict]:
    """加载站点编码表"""
    global _stations_cache, _stations_cache_time

    if _stations_cache and time.time() - _stations_cache_time < STATIONS_CACHE_TTL:
        return _stations_cache

    # 尝试从本地文件加载
    stations_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'stations.json')
    if os.path.exists(stations_file):
        try:
            with open(stations_file, 'r', encoding='utf-8') as f:
                _stations_cache = json.load(f)
                _stations_cache_time = time.time()
                return _stations_cache
        except Exception as e:
            logger.warning(f"Failed to load stations file: {e}")

    # 如果本地没有，尝试从12306下载
    try:
        import httpx
        url = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
        resp = httpx.get(url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        # 解析站点数据：@bjb|北京北|VAP|beijingbei|bjb|0
        text = resp.text
        stations = {}
        for match in re.finditer(r'@([a-z]+)\|([^\|]+)\|([A-Z]+)\|([a-z]+)\|([a-z]+)\|\d+', text):
            pinyin, name, code, full_pinyin, short_pinyin = match.groups()
            stations[name] = {
                "code": code,
                "pinyin": full_pinyin,
                "short_pinyin": short_pinyin
            }

        # 保存到本地
        os.makedirs(os.path.dirname(stations_file), exist_ok=True)
        with open(stations_file, 'w', encoding='utf-8') as f:
            json.dump(stations, f, ensure_ascii=False, indent=2)

        _stations_cache = stations
        _stations_cache_time = time.time()
        return stations
    except Exception as e:
        logger.error(f"Failed to download stations: {e}")
        return {}


def _get_station_code(city_name: str) -> Optional[str]:
    """获取城市对应的站点编码"""
    stations = _load_stations()

    # 直接匹配
    if city_name in stations:
        return stations[city_name]["code"]

    # 模糊匹配：检查城市名是否包含在站点名中
    for name, info in stations.items():
        if city_name in name or name in city_name:
            return info["code"]

    return None


def _get_cached(key: str) -> Optional[Any]:
    """获取缓存"""
    if key in _query_cache:
        result, ts = _query_cache[key]
        if time.time() - ts < QUERY_CACHE_TTL:
            return result
        del _query_cache[key]
    return None


def _set_cached(key: str, result: Any):
    """设置缓存"""
    _query_cache[key] = (result, time.time())


class TrainTicketAgent(AgentBase):
    """火车票查询智能体"""

    def __init__(self, name: str = "TrainTicketAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model

    @cached("train_ticket", ttl=300)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        print(f"[TRAIN-TICKET] reply() called", flush=True)
        if x is None:
            print(f"[TRAIN-TICKET] x is None", flush=True)
            return Msg(name=self.name, content=json.dumps({"error": "No input"}), role="assistant")

        # 解析输入
        content = x.content if not isinstance(x, list) else x[-1].content
        print(f"[TRAIN-TICKET] content type: {type(content)}, length: {len(str(content))}", flush=True)
        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or content
                fast_params = data.get("fast_train_ticket")
                print(f"[TRAIN-TICKET] parsed - user_query: {user_query}, fast_params: {fast_params}", flush=True)
            except json.JSONDecodeError:
                user_query = content
                fast_params = None
                print(f"[TRAIN-TICKET] JSON parse failed, using raw content", flush=True)
        else:
            user_query = str(content)
            fast_params = None

        # 分析查询意图
        query_type = self._detect_query_type(user_query)
        print(f"[TRAIN-TICKET] query_type: {query_type}", flush=True)

        try:
            if query_type == "search_station":
                result = await self._search_station(user_query)
            elif query_type == "route_stations":
                result = await self._query_route_stations(user_query)
            elif query_type == "transfer":
                result = await self._query_transfer(user_query)
            elif query_type == "price":
                result = await self._query_price(user_query)
            else:
                result = await self._query_tickets(user_query, fast_params)
            print(f"[TRAIN-TICKET] result: {json.dumps(result, ensure_ascii=False)[:200]}", flush=True)
        except Exception as e:
            logger.error(f"Train ticket query failed: {e}")
            print(f"[TRAIN-TICKET] exception: {e}", flush=True)
            result = {
                "query_type": query_type,
                "query_success": False,
                "results": {"message": f"查询失败: {str(e)}"}
            }

        final_content = json.dumps(result, ensure_ascii=False)
        print(f"[TRAIN-TICKET] returning content length: {len(final_content)}", flush=True)
        return Msg(name=self.name, content=final_content, role="assistant")

    def _detect_query_type(self, query: str) -> str:
        """检测查询类型"""
        q = query.strip()

        if re.search(r"(搜|查|找).*站", q):
            return "search_station"
        if re.search(r"(经停|停靠|经过|路过).*站", q):
            return "route_stations"
        if re.search(r"(换乘|转车|中转)", q):
            return "transfer"
        if re.search(r"(票价|多少钱|价格)", q):
            return "price"
        return "tickets"

    async def _query_tickets(self, query: str, fast_params: Optional[Dict] = None) -> Dict[str, Any]:
        """查询余票"""
        import asyncio
        try:
            import httpx
        except ImportError:
            return {
                "query_type": "余票查询",
                "query_success": False,
                "results": {"message": "需要安装 httpx: pip install httpx"}
            }

        # 提取出发地、目的地、日期
        if fast_params:
            from_city = fast_params.get("from", "")
            to_city = fast_params.get("to", "")
            date_str = fast_params.get("date", "")
        else:
            from_city, to_city, date_str = self._extract_travel_params(query)

        if not from_city or not to_city:
            return {
                "query_type": "余票查询",
                "query_success": False,
                "results": {"message": "请说明出发地和目的地，如：北京到上海的高铁"}
            }

        # 获取站点编码
        from_code = _get_station_code(from_city)
        to_code = _get_station_code(to_city)

        if not from_code:
            return {
                "query_type": "余票查询",
                "query_success": False,
                "results": {"message": f"未找到出发地: {from_city}"}
            }
        if not to_code:
            return {
                "query_type": "余票查询",
                "query_success": False,
                "results": {"message": f"未找到目的地: {to_city}"}
            }

        # 处理日期
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        elif date_str in ["明天", "明日"]:
            date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_str in ["后天"]:
            date_str = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        elif re.match(r"^\d{1,2}$", date_str):
            # 只有日期，补全月份和年份
            day = int(date_str)
            now = datetime.now()
            if day < now.day:
                # 如果日期已过，认为是下个月
                next_month = now.month + 1
                if next_month > 12:
                    next_month = 1
                    date_str = f"{now.year + 1}-{next_month:02d}-{day:02d}"
                else:
                    date_str = f"{now.year}-{next_month:02d}-{day:02d}"
            else:
                date_str = f"{now.year}-{now.month:02d}-{day:02d}"

        # 检查缓存
        cache_key = f"tickets:{from_code}:{to_code}:{date_str}"
        cached = _get_cached(cache_key)
        if cached:
            print(f"[TRAIN-TICKET] returning cached result", flush=True)
            return cached

        # 调用12306 API
        url = "https://kyfw.12306.cn/otn/leftTicket/queryZ"
        params = {
            "leftTicketDTO.train_date": date_str,
            "leftTicketDTO.from_station": from_code,
            "leftTicketDTO.to_station": to_code,
            "purpose_codes": "ADULT"
        }
        print(f"[TRAIN-TICKET] calling 12306 API: {url}", flush=True)
        print(f"[TRAIN-TICKET] params: {params}", flush=True)

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
                }
            ) as client:
                # 先访问首页获取Cookie
                await client.get("https://kyfw.12306.cn/otn/login/init")
                # 再查询余票
                resp = await client.get(url, params=params)
                print(f"[TRAIN-TICKET] response status: {resp.status_code}", flush=True)
                resp.raise_for_status()
                data = resp.json()
                print(f"[TRAIN-TICKET] response data keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}", flush=True)
        except Exception as e:
            logger.warning(f"12306 API request failed: {e}")
            print(f"[TRAIN-TICKET] API exception: {e}", flush=True)
            return {
                "query_type": "余票查询",
                "query_success": False,
                "results": {"message": f"12306接口暂时不可用: {e}"}
            }

        # 解析结果
        try:
            if data.get("httpstatus") != 200 or not data.get("data"):
                return {
                    "query_type": "余票查询",
                    "query_success": False,
                    "results": {"message": "查询失败，请稍后再试"}
                }

            station_map = data["data"].get("map", {})
            results = data["data"].get("result", [])
            print(f"[TRAIN-TICKET] station_map keys: {list(station_map.keys())[:5]}", flush=True)
            print(f"[TRAIN-TICKET] results count: {len(results)}", flush=True)

            trains = []
            for item in results[:15]:  # 最多显示15条
                parts = item.split("|")
                if len(parts) < 32:
                    continue

                train_no = parts[3]  # 车次
                from_station = station_map.get(parts[6], parts[6])  # 出发站
                to_station = station_map.get(parts[7], parts[7])  # 到达站
                depart_time = parts[8]  # 出发时间
                arrive_time = parts[9]  # 到达时间
                duration = parts[10]  # 历时

                # 座位信息
                second_class = parts[30] or "无"  # 二等座
                first_class = parts[31] or "无"  # 一等座
                business = parts[32] or "无"  # 商务座
                hard_sleeper = parts[28] or "无"  # 硬卧
                soft_sleeper = parts[23] or "无"  # 软卧
                hard_seat = parts[29] or "无"  # 硬座
                no_seat = parts[26] or "无"  # 无座

                # 判断车次类型
                train_type = "其他"
                if train_no.startswith("G"):
                    train_type = "高铁"
                elif train_no.startswith("D"):
                    train_type = "动车"
                elif train_no.startswith("C"):
                    train_type = "城际"
                elif train_no.startswith("K"):
                    train_type = "快速"
                elif train_no.startswith("T"):
                    train_type = "特快"
                elif train_no.startswith("Z"):
                    train_type = "直达"

                trains.append({
                    "train_no": train_no,
                    "train_type": train_type,
                    "from_station": from_station,
                    "to_station": to_station,
                    "depart_time": depart_time,
                    "arrive_time": arrive_time,
                    "duration": duration,
                    "second_class": second_class,
                    "first_class": first_class,
                    "business": business,
                    "hard_sleeper": hard_sleeper,
                    "soft_sleeper": soft_sleeper,
                    "hard_seat": hard_seat,
                    "no_seat": no_seat
                })

            # 构建摘要
            summary_parts = [f"{from_city}→{to_city} ({date_str})"]
            if trains:
                summary_parts.append(f"共{len(trains)}趟列车")
                # 列出前3趟
                for t in trains[:3]:
                    summary_parts.append(f"{t['train_no']} {t['depart_time']}-{t['arrive_time']} 二等座{t['second_class']}")
            else:
                summary_parts.append("暂无余票")

            summary_text = "；".join(summary_parts)
            result = {
                "query_type": "余票查询",
                "query_success": True,
                "answer": summary_text,
                "proactive_question": f"需要我帮你看看{to_city}的住宿和天气吗？",
                "results": {
                    "summary": summary_text,
                    "trains": trains,
                    "total": len(trains),
                    "date": date_str,
                    "from": from_city,
                    "to": to_city
                }
            }

            # 缓存结果
            _set_cached(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Parse 12306 response failed: {e}")
            return {
                "query_type": "余票查询",
                "query_success": False,
                "results": {"message": "数据解析失败"}
            }

    async def _query_price(self, query: str) -> Dict[str, Any]:
        """查询票价"""
        # 从查询中提取车次
        match = re.search(r"([GDCZTK]\d+)", query)
        if not match:
            return {
                "query_type": "票价查询",
                "query_success": False,
                "results": {"message": "请说明车次，如：G1次列车多少钱"}
            }

        train_no = match.group(1)

        # 提取出发地和目的地（如果有的话）
        from_city, to_city, _ = self._extract_travel_params(query)

        return {
            "query_type": "票价查询",
            "query_success": True,
            "results": {
                "summary": f"{train_no}次列车票价查询",
                "message": "票价查询功能正在开发中，请访问12306官网查询",
                "train_no": train_no,
                "from": from_city,
                "to": to_city
            }
        }

    async def _search_station(self, query: str) -> Dict[str, Any]:
        """搜索车站"""
        # 提取关键词
        match = re.search(r"(?:搜|查|找)(.*?)(?:站|$)", query)
        keyword = match.group(1).strip() if match else query

        stations = _load_stations()
        results = []

        for name, info in stations.items():
            if keyword in name or keyword in info.get("pinyin", "") or keyword in info.get("short_pinyin", ""):
                results.append({
                    "name": name,
                    "code": info["code"],
                    "pinyin": info.get("pinyin", "")
                })

        return {
            "query_type": "车站搜索",
            "query_success": True,
            "results": {
                "summary": f"找到{len(results)}个匹配站点",
                "stations": results[:20],
                "keyword": keyword
            }
        }

    async def _query_route_stations(self, query: str) -> Dict[str, Any]:
        """查询经停站"""
        match = re.search(r"([GDCZTK]\d+)", query)
        if not match:
            return {
                "query_type": "经停站查询",
                "query_success": False,
                "results": {"message": "请说明车次，如：G1经过哪些站"}
            }

        train_no = match.group(1)

        return {
            "query_type": "经停站查询",
            "query_success": True,
            "results": {
                "summary": f"{train_no}次列车经停站查询",
                "message": "经停站查询功能正在开发中，请访问12306官网查询",
                "train_no": train_no
            }
        }

    async def _query_transfer(self, query: str) -> Dict[str, Any]:
        """中转换乘查询"""
        from_city, to_city, date_str = self._extract_travel_params(query)

        if not from_city or not to_city:
            return {
                "query_type": "中转换乘",
                "query_success": False,
                "results": {"message": "请说明出发地和目的地，如：拉萨到三亚怎么转车"}
            }

        return {
            "query_type": "中转换乘",
            "query_success": True,
            "results": {
                "summary": f"{from_city}→{to_city}中转换乘方案",
                "message": "中转换乘查询功能正在开发中，请访问12306官网查询",
                "from": from_city,
                "to": to_city
            }
        }

    def _extract_travel_params(self, query: str):
        """从查询中提取出发地、目的地、日期"""
        q = query.strip()

        # 提取日期
        date_str = ""
        date_patterns = [
            (r"(\d{4}-\d{1,2}-\d{1,2})", lambda m: m.group(1)),
            (r"(\d{1,2}月\d{1,2}[日号])", lambda m: self._convert_chinese_date(m.group(1))),
            (r"(明天|明日|后天|大后天)", lambda m: m.group(1)),
            (r"(\d{1,2})[日号]", lambda m: m.group(1)),
        ]
        for pattern, converter in date_patterns:
            match = re.search(pattern, q)
            if match:
                date_str = converter(match)
                break

        # 提取出发地和目的地
        from_city = ""
        to_city = ""

        # 模式1：XX到XX
        match = re.search(r"([一-龥]{2,6})\s*[到至去往]\s*([一-龥]{2,6})", q)
        if match:
            from_city = match.group(1)
            to_city = match.group(2)

        # 模式2：从XX出发到XX
        if not from_city:
            match = re.search(r"从\s*([一-龥]{2,6}).*?[到至去往]\s*([一-龥]{2,6})", q)
            if match:
                from_city = match.group(1)
                to_city = match.group(2)

        return from_city, to_city, date_str

    def _convert_chinese_date(self, date_str: str) -> str:
        """转换中文日期为标准格式"""
        match = re.search(r"(\d{1,2})月(\d{1,2})[日号]", date_str)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            now = datetime.now()
            year = now.year
            if month < now.month or (month == now.month and day < now.day):
                year += 1
            return f"{year}-{month:02d}-{day:02d}"
        return date_str
