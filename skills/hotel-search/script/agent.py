"""
酒店/餐厅搜索智能体 - HotelSearchAgent
使用高德 POI 搜索 API (place/text) 搜索住宿和餐饮信息。

依赖：
- AMAP_API_KEY 需在 .env 中配置
- 无需额外 pip 依赖（使用 subprocess + curl）
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import asyncio
import json
import logging
import re
import subprocess
from urllib.parse import quote

from utils.skill_loader import SkillLoader

logger = logging.getLogger(__name__)

# 住宿类型关键词（按长度降序，优先长匹配）
_ACCOMMODATION_KEYWORDS = sorted([
    "青年旅舍", "招待所", "民宿", "客栈", "宾馆", "旅馆", "酒店", "青旅",
], key=lambda x: -len(x))

# 中国主要城市列表（含地级市，用于从查询中提取城市名）
_COMMON_CITIES = [
    # 直辖市 / 省会
    "北京", "上海", "天津", "重庆",
    "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州",
    "长沙", "郑州", "济南", "哈尔滨", "沈阳", "昆明", "合肥", "福州",
    "石家庄", "南昌", "贵阳", "太原", "南宁", "海口", "呼和浩特",
    "乌鲁木齐", "拉萨", "银川", "西宁", "兰州",
    # 计划单列市 / 经济特区
    "厦门", "青岛", "大连", "宁波", "珠海", "汕头",
    # 珠三角
    "东莞", "佛山", "惠州", "中山", "江门", "肇庆", "潮州", "揭阳",
    "汕尾", "河源", "梅州", "清远", "阳江", "茂名", "湛江", "云浮", "韶关",
    # 长三角
    "无锡", "常州", "徐州", "温州", "绍兴", "嘉兴", "扬州", "南通",
    "镇江", "泰州", "盐城", "淮安", "连云港", "宿迁", "湖州", "金华",
    "衢州", "舟山", "台州", "丽水", "芜湖", "马鞍山",
    # 山东 / 福建
    "烟台", "潍坊", "威海", "日照", "临沂", "淄博", "济宁", "泰安",
    "泉州", "漳州", "龙岩", "三明", "莆田", "宁德", "南平",
    # 华中 / 西南
    "洛阳", "开封", "南阳", "许昌", "新乡", "宜昌", "襄阳", "荆州",
    "绵阳", "德阳", "宜宾", "南充", "泸州", "遵义", "曲靖", "玉溪",
    # 东北 / 西北
    "长春", "吉林", "齐齐哈尔", "大庆", "鞍山", "锦州",
    "咸阳", "宝鸡", "榆林", "酒泉",
    # 广西 / 海南 / 内蒙古
    "桂林", "柳州", "北海", "防城港",
    "三亚", "儋州", "琼海",
    "包头", "鄂尔多斯", "赤峰",
    # 旅游城市
    "丽江", "大理", "黄山", "张家界", "凤凰", "九寨沟", "峨眉山",
    "秦皇岛", "承德", "九江", "景德镇", "岳阳", "延安",
]


# 餐饮类型关键词（按长度降序，优先长匹配）
_RESTAURANT_KEYWORDS = sorted([
    "日本料理", "韩国料理", "泰国菜", "越南菜", "印度菜",
    "麻辣烫", "大排档", "自助餐", "烧烤", "火锅", "川菜", "粤菜", "湘菜",
    "日料", "韩餐", "西餐", "早茶", "点心", "海鲜", "烤鸭", "串串",
    "小吃", "快餐", "面馆", "粉店", "粥店",
    "餐厅", "美食", "好吃", "吃饭", "聚餐", "夜宵", "午餐", "晚餐", "午饭", "晚饭",
    "特色菜", "土菜", "农家菜", "私房菜", "本帮菜",
], key=lambda x: -len(x))

# 非餐饮查询关键词（优先于餐饮匹配）
_NON_RESTAURANT_KEYWORDS = [
    "酒店", "民宿", "宾馆", "旅馆", "客栈", "青旅", "青年旅舍", "招待所", "住宿",
]


class HotelSearchAgent(AgentBase):
    """
    酒店/餐厅搜索智能体

    核心功能：
    - 从用户查询中提取城市和搜索参数
    - 自动识别酒店/餐厅查询类型
    - 调用高德 POI 搜索 API (place/text) 查询住宿或餐饮
    - 返回结构化列表 + 纯文本摘要
    """

    def __init__(self, name: str = "HotelSearchAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(
                name=self.name,
                content=json.dumps({"query_success": False, "results": {"message": "输入为空"}}),
                role="assistant",
            )

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

        is_restaurant = self._is_restaurant_query(user_query)
        query_type = "餐厅搜索" if is_restaurant else "酒店搜索"
        logger.info(f"{query_type} query: {user_query}")

        try:
            city = self._extract_city(user_query)
            if not city:
                hint = "未识别到城市，请说明具体城市，如：北京有哪些酒店？" if not is_restaurant else "未识别到城市，请说明具体城市，如：北京有哪些好吃的？"
                return Msg(
                    name=self.name,
                    content=json.dumps({
                        "query_type": query_type,
                        "query_success": False,
                        "results": {"message": hint},
                    }, ensure_ascii=False),
                    role="assistant",
                )

            if is_restaurant:
                params = self._extract_food_params(user_query, city)
                result = await self._restaurant_search(city, params)
            else:
                params = self._extract_search_params(user_query, city)
                result = await self._hotel_search(city, params)

            self._add_proactive_question(result, city, is_restaurant)

            return Msg(
                name=self.name,
                content=json.dumps(result, ensure_ascii=False),
                role="assistant",
            )
        except Exception as e:
            logger.error(f"{query_type} failed: {e}")
            return Msg(
                name=self.name,
                content=json.dumps({
                    "query_type": query_type,
                    "query_success": False,
                    "results": {"message": f"搜索失败: {str(e)}"},
                }, ensure_ascii=False),
                role="assistant",
            )

    def _add_proactive_question(self, result: Dict, city: str, is_restaurant: bool = False) -> None:
        if result.get("query_success"):
            if is_restaurant:
                result["proactive_question"] = f"需要我帮你查一下{city}的酒店或天气吗？"
            else:
                result["proactive_question"] = f"需要我帮你查一下{city}的天气和交通吗？"

    # ── 查询类型识别 ──

    def _is_restaurant_query(self, query: str) -> bool:
        """判断查询是否为餐厅/美食搜索。非餐饮关键词优先（避免"XX酒店附近的美食"误判）。"""
        q = (query or "").strip()
        # 非餐饮关键词优先检查
        for kw in _NON_RESTAURANT_KEYWORDS:
            if kw in q:
                # 如果同时有"附近的美食""周边的餐厅"等修饰，仍为餐厅查询
                after_kw = q[q.index(kw) + len(kw):]
                if any(rk in after_kw for rk in ["附近", "周边", "旁边", "楼下", "对面"]):
                    continue
                # 检查是否有餐厅词在住宿词前面
                before_kw = q[:q.index(kw)]
                if any(rk in before_kw for rk in _RESTAURANT_KEYWORDS):
                    continue
                return False
        # 检查餐饮关键词
        for kw in _RESTAURANT_KEYWORDS:
            if kw in q:
                return True
        return False

    def _extract_food_params(self, query: str, city: str = "") -> Dict[str, Any]:
        """
        从查询中提取餐饮搜索偏好。
        返回: {"keywords": str}
        """
        params: Dict[str, Any] = {"keywords": "美食"}

        # 检测具体菜系/餐饮类型
        for kw in _RESTAURANT_KEYWORDS:
            if kw in query:
                # 跳过通用餐饮词
                if kw in ("午餐", "晚餐", "午饭", "晚饭", "吃饭", "聚餐",
                          "好吃", "美食", "餐厅", "夜宵", "特色菜"):
                    continue
                params["keywords"] = kw
                break

        # 提取位置限定（先清理餐饮通用词，避免污染 location 提取）
        clean_query = query
        for word in ["好吃的", "好吃", "美食", "吃饭", "聚餐", "餐厅", "推荐",
                     "有没有", "有哪些", "有什么", "帮我找", "帮我查", "搜索", "找一下",
                     "查一下", "附近", "周边", "哪家", "哪个", "哪里",
                     "的", "吗", "呢", "啊", "吧", "?", "？", "啥", "有啥"]:
            clean_query = clean_query.replace(word, " ")
        location_parts = self._extract_location_context(clean_query, city)
        if location_parts:
            params["keywords"] = f"{location_parts} {params['keywords']}"

        return params

    async def _restaurant_search(self, city: str, params: Dict) -> Dict[str, Any]:
        """调用高德 POI 搜索 API 查询餐厅。"""
        from config import AMAP_CONFIG

        api_key = AMAP_CONFIG.get("api_key", "")
        if not api_key:
            raise ValueError("AMAP_API_KEY 未配置，请在 .env 中设置")

        url = f"{AMAP_CONFIG.get('base_url', 'https://restapi.amap.com/v3')}/place/text"

        query_params = {
            "key": api_key,
            "keywords": params["keywords"],
            "city": city,
            "offset": "15",
            "page": "1",
            "extensions": "all",
            "citylimit": "true",
        }

        query_str = "&".join(f"{k}={quote(str(v))}" for k, v in query_params.items())
        full_url = f"{url}?{query_str}"

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._curl_get, full_url)

        if data.get("status") != "1":
            raise ValueError(f"POI 搜索接口返回错误: {data.get('info', '未知错误')}")

        count_str = data.get("count", "0")
        count = int(count_str) if count_str.isdigit() else 0
        pois = data.get("pois", [])

        return await self._build_restaurant_result(city, params["keywords"], count, pois)

    async def _build_restaurant_result(
        self, city: str, keyword: str, count: int, pois: List[Dict]
    ) -> Dict[str, Any]:
        restaurants = []
        for p in pois[:15]:
            photos = p.get("photos", [])
            photo_url = photos[0].get("url", "") if photos else ""
            biz_ext = p.get("biz_ext", {}) or {}

            restaurants.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "address": p.get("address", ""),
                "rating": biz_ext.get("rating", ""),
                "cost": biz_ext.get("cost", ""),
                "tel": (p.get("tel", "") or ""),
                "photo": photo_url,
                "distance": p.get("distance", ""),
                "type": p.get("type", ""),
                "location": p.get("location", ""),
            })

        # 按评分降序排列
        restaurants.sort(key=lambda r: float(r.get("rating") or 0), reverse=True)

        # Amap count 上限为 600
        display_count = count if count < 600 else count

        summary = self._generate_restaurant_summary(city, keyword, count, restaurants)

        return {
            "query_type": "餐厅搜索",
            "query_success": True,
            "results": {
                "city": city,
                "keyword": keyword,
                "count": display_count,
                "summary": summary,
                "restaurants": restaurants,
                "sources": [{"title": "高德地图", "url": "https://www.amap.com"}],
            },
        }

    def _generate_restaurant_summary(
        self, city: str, keyword: str, count: int, restaurants: List[Dict]
    ) -> str:
        """生成餐厅搜索纯文本摘要。"""
        if not restaurants:
            return f"{city}暂未找到「{keyword}」相关餐厅"

        top3 = restaurants[:3]
        names = "、".join(r["name"] for r in top3)
        if count >= 600:
            return f"{city}找到600+家{keyword}（显示评分最高的前15家），排名靠前的包括：{names}。如需按菜系或价格筛选，请告诉我。"
        return f"{city}共有{count}家{keyword}，评分最高的包括：{names}。如需按菜系或价格筛选，请告诉我。"

    # ── 城市提取 ──

    def _extract_city(self, query: str) -> str:
        """从查询中提取城市名，仅匹配已知城市列表。"""
        q = (query or "").strip()
        for city in _COMMON_CITIES:
            if city in q:
                return city
        return ""

    # ── 位置限定提取 ──

    def _extract_location_context(self, query: str, city: str) -> str:
        """
        从查询中提取区/镇/街道级位置限定词，用于拼入 API keywords 实现精准搜索。
        如 "揭阳市揭东区锡场镇附近" → city="揭阳", 返回 "揭东区锡场镇附近"
        """
        # 移除已识别的城市名 + 住宿关键词，剩余为位置候选
        q = query
        if city:
            # 移除 "XX市" 前缀（如 "揭阳市" → 移除前3字）
            q = re.sub(rf"{city}市?", "", q)

        # 移除住宿类型关键词
        for kw in _ACCOMMODATION_KEYWORDS:
            q = q.replace(kw, "")

        # 移除疑问词 / 动词 / 量词
        for word in ["有没有", "有哪些", "有什么", "帮我找", "帮我查", "搜索", "找一下",
                       "查一下", "推荐", "附近", "周边", "有没有", "哪家", "哪个",
                       "的", "吗", "呢", "啊", "吧", "有", "?", "？"]:
            q = q.replace(word, " ")

        # 提取区/镇/县/街道/路/景点/地标 级别的行政或地理名称
        location_match = re.search(
            r"([一-龥]{2,6}(?:区|镇|县|乡|街道|路|街|村|景区|公园|广场|站|商圈"
            r"|大学|学院|中学|小学|学校|医院|大厦|大楼|商场|购物中心"
            r"|地铁站|火车站|机场|码头|汽车站|高铁站"
            r"|山|湖|河|海|寺|庙|塔|桥|塔|宫|陵|墓))",
            q,
        )
        # 未匹配行政/地标后缀，尝试匹配"XX旁边/附近/周边"模式
        if not location_match:
            location_match = re.search(
                r"([一-龥]{2,10})(?:旁边|附近|周边|对面|楼下|边上|一带|附近一带|跟前)",
                q,
            )
        if location_match:
            # 截取匹配位置及前后上下文
            start = max(0, location_match.start() - 2)
            end = min(len(q), location_match.end() + 4)
            context = q[start:end].strip()
            # 清理多余空格
            context = re.sub(r"\s+", "", context)
            if context:
                return context

        return ""

    def _extract_search_params(self, query: str, city: str = "") -> Dict[str, Any]:
        """
        从查询中提取搜索偏好。
        返回: {"keywords": str, "star": str|None, "price_range": str|None}
        """
        params: Dict[str, Any] = {
            "keywords": "酒店",
            "star": None,
            "price_range": None,
        }

        # 检测住宿类型关键词
        for kw in _ACCOMMODATION_KEYWORDS:
            if kw in query:
                params["keywords"] = kw
                break

        # 提取品牌名（优先级高于类型关键词）
        brand_match = re.search(
            r"(汉庭|如家|全季|万豪|希尔顿|洲际|喜来登|凯悦|丽思|温德姆|"
            r"锦江|格林|尚客优|七天|速8|智选|假日|亚朵|桔子|维也纳|和颐|漫心)",
            query,
        )
        if brand_match:
            params["keywords"] = brand_match.group(1)

        # 提取位置限定（XX区 / XX镇 / XX县 / XX街道 / XX路 / XX附近 / XX周边）
        location_parts = self._extract_location_context(query, city)
        if location_parts:
            # 将位置限定拼接在关键词前面，让 API 精准搜索
            params["keywords"] = f"{location_parts} {params['keywords']}"

        # 提取星级
        star_match = re.search(r"([一二三四五1-5])\s*[星星]级", query)
        if star_match:
            star_str = star_match.group(1)
            star_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5"}
            params["star"] = star_map.get(star_str, star_str)

        # 提取价格区间
        price_match = re.search(r"(\d+)\s*[-–—到至]\s*(\d+)\s*元?", query)
        if price_match:
            params["price_range"] = f"{price_match.group(1)}-{price_match.group(2)}"
        else:
            price_match = re.search(r"(\d+)\s*元?\s*(左右|以内|以下)", query)
            if price_match:
                amount = price_match.group(1)
                if "以内" in price_match.group(2) or "以下" in price_match.group(2):
                    params["price_range"] = f"0-{amount}"
                else:
                    params["price_range"] = f"{int(amount) * 0.7:.0f}-{int(amount) * 1.3:.0f}"

        return params

    # ── API 调用 ──

    async def _hotel_search(self, city: str, params: Dict) -> Dict[str, Any]:
        """
        调用高德 POI 搜索 API (place/text)。
        注意：不使用 types 参数（高德住宿分类码已废弃，会导致空结果）。
        """
        from config import AMAP_CONFIG

        api_key = AMAP_CONFIG.get("api_key", "")
        if not api_key:
            raise ValueError("AMAP_API_KEY 未配置，请在 .env 中设置")

        url = f"{AMAP_CONFIG.get('base_url', 'https://restapi.amap.com/v3')}/place/text"

        query_params = {
            "key": api_key,
            "keywords": params["keywords"],
            "city": city,
            "offset": "15",
            "page": "1",
            "extensions": "all",
            "citylimit": "true",
        }

        query_str = "&".join(f"{k}={quote(str(v))}" for k, v in query_params.items())
        full_url = f"{url}?{query_str}"

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._curl_get, full_url)

        if data.get("status") != "1":
            raise ValueError(f"POI 搜索接口返回错误: {data.get('info', '未知错误')}")

        count_str = data.get("count", "0")
        count = int(count_str) if count_str.isdigit() else 0
        pois = data.get("pois", [])

        # 后过滤：星级 / 价格
        if params.get("star") and pois:
            pois = self._filter_by_star(pois, params["star"])
        if params.get("price_range") and pois:
            pois = self._filter_by_price(pois, params["price_range"])

        return await self._build_result(city, params["keywords"], count, pois)

    @staticmethod
    def _curl_get(full_url: str) -> dict:
        r = subprocess.run(
            ["curl", "-s", "--compressed", full_url],
            capture_output=True, text=True, timeout=20, encoding="utf-8",
        )
        return json.loads(r.stdout)

    # ── 后过滤 ──

    @staticmethod
    def _filter_by_star(pois: List[Dict], star: str) -> List[Dict]:
        """按星级过滤。星级信息在高德 type 字段中（如"五星级酒店"）。"""
        target_star = int(star)
        star_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
        filtered = []
        for p in pois:
            poi_type = p.get("type", "")
            matched = False
            for part in poi_type.split(";"):
                sm = re.search(r"([一二三四五1-5])\s*[星星]级", part)
                if sm:
                    s = sm.group(1)
                    poi_star = star_map.get(s, int(s) if s.isdigit() else 0)
                    if poi_star >= target_star:
                        filtered.append(p)
                    matched = True
                    break
            if not matched:
                filtered.append(p)
        return filtered if filtered else pois

    @staticmethod
    def _filter_by_price(pois: List[Dict], price_range: str) -> List[Dict]:
        """按价格区间过滤。高德 biz_ext.cost 如 '298-598'。"""
        parts = price_range.split("-")
        min_p = int(parts[0]) if parts[0] else 0
        max_p = int(parts[1]) if len(parts) > 1 and parts[1] else 99999
        filtered = []
        for p in pois:
            cost_str = ((p.get("biz_ext") or {}).get("cost") or "")
            if cost_str:
                costs = cost_str.replace("￥", "").replace("¥", "").split("-")
                try:
                    avg = (int(costs[0]) + int(costs[-1])) / 2
                    if min_p <= avg <= max_p:
                        filtered.append(p)
                        continue
                except (ValueError, IndexError):
                    pass
            filtered.append(p)
        return filtered if filtered else pois

    # ── 结果构建 ──

    async def _build_result(
        self, city: str, keyword: str, count: int, pois: List[Dict]
    ) -> Dict[str, Any]:
        hotels = []
        for p in pois[:15]:
            photos = p.get("photos", [])
            photo_url = photos[0].get("url", "") if photos else ""
            biz_ext = p.get("biz_ext", {}) or {}

            hotels.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "address": p.get("address", ""),
                "rating": biz_ext.get("rating", ""),
                "cost": biz_ext.get("cost", ""),
                "tel": (p.get("tel", "") or ""),
                "photo": photo_url,
                "distance": p.get("distance", ""),
                "type": p.get("type", ""),
                "location": p.get("location", ""),
            })

        # 按评分降序排列
        hotels.sort(key=lambda h: float(h.get("rating") or 0), reverse=True)

        # Amap count 上限为 600
        display_count = count if count < 600 else count

        summary = await self._generate_summary(city, keyword, count, hotels)

        return {
            "query_type": "酒店搜索",
            "query_success": True,
            "results": {
                "city": city,
                "keyword": keyword,
                "count": display_count,
                "summary": summary,
                "hotels": hotels,
                "sources": [{"title": "高德地图", "url": "https://www.amap.com"}],
            },
        }

    async def _generate_summary(
        self, city: str, keyword: str, count: int, hotels: List[Dict]
    ) -> str:
        """生成纯文本摘要（不依赖 LLM，避免流式响应兼容问题）。"""
        if not hotels:
            return f"{city}暂未找到「{keyword}」相关信息"

        # 取前 3 家高评分酒店
        top3 = hotels[:3]

        names = "、".join(h["name"] for h in top3)
        if count >= 600:
            return f"{city}找到600+家{keyword}（显示评分最高的前15家），排名靠前的包括：{names}。如需按品牌、星级或价格筛选，请告诉我。"
        return f"{city}共有{count}家{keyword}，评分最高的包括：{names}。如需按品牌、星级或价格筛选，请告诉我。"
