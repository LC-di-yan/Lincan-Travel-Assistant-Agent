"""城市常规交通建议；不冒充实时路况、路线规划或票价查询。"""
import re

TRANSPORT_ROUTE_QUESTION = "你的具体起点和终点是哪里，更在意省钱还是少换乘？"
TRANSPORT_TIME_QUESTION = "你计划何时出发，更在意省钱还是少换乘？"


def is_transport_question_echo(text: str) -> bool:
    """Recognize the exact assistant hints that old clients could send back."""
    return text.strip().rstrip("。？?") in {
        question.rstrip("？") for question in (TRANSPORT_ROUTE_QUESTION, TRANSPORT_TIME_QUESTION)
    }


_CITY_GUIDES = {
    "北京": ("城区跨区出行优先比较地铁，时间通常比路面交通更容易安排；行李多、多人同行或站外最后一段可考虑出租车/网约车。前往机场要先区分首都机场和大兴机场，核对接驳线路及当日运营时间。", "https://www.bjsubway.com/"),
    "上海": ("市内跨区出行优先比较地铁，短距离可结合步行；行李多或夜间轨道停运后可考虑正规出租车/网约车。机场出行要区分虹桥与浦东，按实际出发点核对轨道接驳和运营时间。", "https://www.shmetro.com/"),
    "重庆": ("跨区出行优先比较轨道交通；山地道路坡度和高差较大，步行导航距离短也可能需要爬坡或上下楼，需核对车站出入口与实际楼层。行李多或爬坡较多的最后一段可考虑出租车/网约车，不宜仅按直线距离选步行或骑行。", "https://www.cqmetro.cn/"),
    "杭州": ("城区与交通枢纽之间可优先比较地铁；西湖周边按实际目的地结合公交和步行，进入游览区前核对交通管制及站点。远距离郊区出行不能只参考市中心交通方式，需单独比较公交衔接或出租车。", "https://www.hzmetro.com/"),
    "深圳": ("跨区及枢纽之间优先比较地铁；城市跨度较大，应按实际目的地安排换乘，不能把不同区域视为短途。站外短途可结合公交、步行或出租车，深夜先核对轨道运营时间。", "https://www.szmc.net/"),
    "成都": ("城区及交通枢纽之间可优先比较地铁，中心城区短途按实际距离衔接步行或公交；前往郊区景点需单独比较接驳，不能直接套用市中心方式。行李多或夜间出行可考虑出租车/网约车。", "https://www.chengdurail.com/"),
}


def needs_transport_advice(query: str) -> bool:
    text = re.sub(r"交通(?:费(?:用)?|补贴|报销|标准)", "", query or "")
    return bool(re.search(r"交通|市内出行|当地出行|出行方式|怎么(?:坐车|出行)|如何出行|地铁(?:推荐|方便)|公交(?:推荐|方便)", text))


def local_transport_advice(city: str, query: str, current: dict | None = None) -> dict:
    """输入已解析城市和可选实况，不从用户文本猜测实时交通数据。"""
    if not city:
        return {"summary": "请补充想了解交通的城市；如需具体路线，也请提供起点、终点和出发时间。", "sources": [], "scope": "clarification"}
    guide, url = _CITY_GUIDES.get(city.removesuffix("市"), (
        "需按当地公共交通实际覆盖选择出行方式：若起终点有便利轨道或公交衔接，可优先比较公共交通；无便利覆盖、携带大件行李或夜间出行，可比较正规出租车/网约车。短途步行或骑行要先核对道路坡度、步行条件及天气。", ""))
    lines = [f"🚇{city}交通推荐（常规出行建议）", guide]
    current = current or {}
    cautions = []
    try:
        temp = float(current.get("temp", ""))
        if -90 <= temp <= 10:
            cautions.append(f"当前气温约{temp:g}℃，尽量减少长时间室外候车和长距离骑行")
    except (TypeError, ValueError):
        pass
    wind = re.findall(r"\d+", str(current.get("wind", "")))
    if wind and max(map(int, wind)) >= 5:
        cautions.append("当前风力偏大，优先考虑有遮蔽的换乘方式，谨慎选择骑行")
    if any(x in str(current.get("weather", "")) for x in ("雨", "雪", "沙", "雾")):
        cautions.append("当前天气不利于长时间露天出行，注意路面与能见度，核对运营和预警信息")
    if cautions:
        lines.append("结合本次天气：" + "；".join(cautions) + "。")
    specific_route = bool(re.search(r"从.+(?:到|去|前往).+", query or ""))
    if specific_route:
        lines.append("以上只是城市层面的方式建议；本次尚未计算你给出的具体路线，请确认出发时间、行李及少换乘/省钱偏好后比较路线。")
    else:
        lines.append("若要进一步选路线，请告诉我起点、终点、出发时间，以及是否有大件行李、优先省钱还是少换乘。")
    lines.append("未查询实时拥堵、封路、具体票价或预计耗时；运营时间与具体路线请以官方或地图当日查询为准。")
    return {"summary": "\n".join(lines), "scope": "city_guidance", "sources": [{"title": f"{city}轨道交通官方信息（核对运营）", "url": url}] if url else []}
