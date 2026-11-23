"""共享天气需求识别，包含依赖实时气温的穿衣问题。"""
import re


def asks_about_clothing(query: str) -> bool:
    text = query or ""
    # 场合、审美类穿搭不能仅凭衣服关键词当作天气问题。
    if re.search(r"婚礼|婚宴|面试|搭配|配色|颜色|买衣服|服装店", text) and not re.search(r"天气|气温|温度|冷不冷|热不热", text):
        return False
    return bool(re.search(r"穿什么(?:衣服)?|穿(?:多少|多厚)|穿衣(?:建议|指数)|(?:要不要|需要|适合|用不用)穿(?:羽绒服|外套|毛衣|短袖|长袖)", text))


def needs_weather(query: str) -> bool:
    return bool(re.search(r"天气|气温|温度|多少度|下雨|下雪|预报|冷不冷|热不热|冷吗|热吗|(?:要不要|需不需要|用不用)带伞", query or "")) or asks_about_clothing(query)
