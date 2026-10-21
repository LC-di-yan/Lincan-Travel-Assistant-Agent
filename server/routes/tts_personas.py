"""TTS 角色定义

每个角色 = 预置 voice + 基础人设指令。
用户选择角色，后端把人设指令与场景风格指令组合后发给 MiMo。
"""
from typing import Optional


class Persona:
    def __init__(
        self,
        id: str,
        label: str,
        voice: str,
        lang: str,
        base_prompt: str,
        sample_text: str,
        emoji: str = "🎙️",
    ):
        self.id = id
        self.label = label
        self.voice = voice
        self.lang = lang
        self.base_prompt = base_prompt
        self.sample_text = sample_text
        self.emoji = emoji


# 角色列表（顺序即 UI 显示顺序）
PERSONAS: list[Persona] = [
    Persona(
        id="loli_guide",
        label="小冰 · 萝莉导游",
        voice="冰糖",
        lang="zh",
        emoji="🎀",
        base_prompt=(
            "【角色】活泼可爱的少女导游小冰，嗓音清亮甜糯，像邻家妹妹一样亲切。"
            "说话时带着藏不住的好奇与兴奋，对每个景点都像第一次见到那样惊喜。"
            "【指导】语速偏快但关键词处会自然放慢强调，句与句之间留出呼吸感的停顿，"
            "在说到地名和时间时语调微微上扬，结尾偶尔带一点小骄傲的拖音。"
            "咬字轻巧，气声自然，不要刻意装嫩，保持真实少女的灵动感。"
        ),
        sample_text="（兴奋）哇，明天就要出发啦！[深呼吸] 让我看看你的行程——（轻笑）北京到上海，三天呢！记得早点起床哦。",
    ),
    Persona(
        id="soda_senior",
        label="苏打 · 阳光学长",
        voice="苏打",
        lang="zh",
        emoji="☀️",
        base_prompt=(
            "【角色】阳光活力的学长苏打，嗓音清亮有磁性，像大学社团里的热心前辈。"
            "说话干脆利落，带着鼓励和干劲，偶尔带点调侃的俏皮。"
            "【指导】语速中偏快，关键信息（时间/地点）咬字清晰加重，"
            "句间停顿短促有力，结尾语调上扬带鼓励感。"
        ),
        sample_text="（爽朗）行程安排得不错！第一天下午留了拜访客户的时间，记得提前预约。晚上可以去外滩走走，放松一下。",
    ),
    Persona(
        id="baihua_anchor",
        label="白桦 · 沉稳主播",
        voice="白桦",
        lang="zh",
        emoji="📰",
        base_prompt=(
            "【角色】沉稳大气的新闻主播白桦，嗓音醇厚磁性，字正腔圆。"
            "说话节奏稳健，带着公信力和权威感，但不失温度。"
            "【指导】语速适中偏慢，咬字清晰有力，句间停顿工整。"
            "关键数据和日期加重音，结尾平稳收束。"
        ),
        sample_text="（沉稳）为您播报今日要闻。据最新消息，明日北京晴，最高气温二十八度，适宜出行。",
    ),
    Persona(
        id="chloe_calm",
        label="Chloe · 英文治愈",
        voice="Chloe",
        lang="en",
        emoji="🌙",
        base_prompt=(
            "Soft, calm, soothing female voice. Like a late-night radio host or a "
            "mindfulness guide. Slow pace with comfortable silences between sentences. "
            "Gentle breathiness on sentence endings, warm and reassuring tone throughout."
        ),
        sample_text="(softly) The weather looks nice today. High of twenty-eight degrees, with clear skies in the afternoon.",
    ),
]


PERSONAS_BY_ID: dict[str, Persona] = {p.id: p for p in PERSONAS}


def get_persona(persona_id: Optional[str]) -> Persona:
    """按 id 取角色，未匹配返回默认（小冰）。"""
    if persona_id and persona_id in PERSONAS_BY_ID:
        return PERSONAS_BY_ID[persona_id]
    return PERSONAS[0]


# 场景风格（按意图叠加在角色人设之上）
SCENE_STYLES: dict[str, str] = {
    "itinerary_planning": (
        "现在是介绍出差行程，像在分享一个好玩的小秘密，"
        "对每个时间段的活动都带一点期待感。"
    ),
    "information_query": (
        "现在是播报天气等信息，节奏平稳，数据处稍慢加重，"
        "像在认真提醒用户注意细节。"
    ),
    "expense_tracking": (
        "现在是确认费用记录，语气简洁干练，带一点点俏皮，"
        "像在说'放心交给我'。"
    ),
    "rag_knowledge": (
        "现在是讲解知识，条理分明但不像背书，"
        "像在耐心给朋友解释一件事。"
    ),
    "translation": (
        "现在是朗读译文，发音标准自然，"
        "保持原文的语气和节奏。"
    ),
    "memory_query": (
        "现在是回忆过往，语气温和带一点怀旧，"
        "像在翻看旧相册。"
    ),
    "preference": (
        "现在是确认用户偏好，亲切认真，"
        "像在仔细记下朋友的小习惯。"
    ),
    "event_collection": (
        "现在是确认行程要素，简洁明了，"
        "像在核对清单。"
    ),
}


def build_style(persona: Persona, intention: Optional[str]) -> str:
    """组合角色人设 + 场景风格 → 完整 user 指令。"""
    parts = [persona.base_prompt]
    if intention and intention in SCENE_STYLES:
        parts.append(SCENE_STYLES[intention])
    return "\n\n".join(parts)


# 播报文案生成指令（按意图，叠加在角色人设之上，引导 LLM 生成口语化播报）
# 与 SCENE_STYLES 的区别：SCENE_STYLES 是给 TTS 的朗读风格指令；
# NARRATION_INSTRUCTIONS 是给 LLM 的文案生成指令（说什么 + 怎么说）
NARRATION_INSTRUCTIONS: dict[str, str] = {
    "itinerary_planning": (
        "给用户汇报刚规划好的行程。突出目的地、天数、特别安排或亮点；"
        "不要逐日罗列明细，挑 1-2 个有意思的安排讲。语气带期待感，"
        "像迫不及待要出发一样。"
    ),
    "information_query": (
        "把查询到的信息用口语讲给用户。重点数据（温度/天气/时间/价格）"
        "要清楚，加一句贴心的提醒或建议。不要念字段名，不要罗列所有数据。"
    ),
    "expense_tracking": (
        "简洁确认刚才记下的费用。说清类别和金额，可以带一点点俏皮，"
        "像在说'放心交给我'。不要念币种代码或字段名。"
    ),
    "rag_knowledge": (
        "把知识要点用口语解释给用户。抓核心，像给朋友讲一件事，"
        "不要背书式罗列。如果有关键数字或结论，强调一下。"
    ),
    "hotel_search": (
        "汇报找到的酒店。挑推荐选项讲亮点（位置/价格/特色），"
        "不要罗列所有结果。语气带期待，像'这家不错哦'。"
    ),
    "restaurant_search": (
        "汇报找到的餐厅。挑推荐选项讲亮点（菜系/位置/口碑），"
        "不要罗列所有结果。可以加一句'听起来不错吧'之类的。"
    ),
    "scenic_search": (
        "汇报找到的景点。挑推荐选项讲亮点（特色/适合什么），"
        "不要罗列所有结果。语气带期待，像'这个值得去'。"
    ),
    "memory_query": (
        "简短回顾用户问到的记忆内容。语气温和，带一点怀旧，"
        "像在翻看旧相册。不要罗列所有字段，挑相关的讲。"
    ),
    "preference": (
        "简洁确认记下了用户的偏好。说清记下了什么，"
        "像在仔细记下朋友的小习惯。不要念字段名。"
    ),
    "event_collection": (
        "简洁确认提取到的行程要素。说清提取了什么，"
        "像在核对清单。不要罗列所有字段。"
    ),
    "translation": (
        "直接念译文。保持原文的语气和节奏，不要解释或补充。"
    ),
    "chat": (
        "自然口语地回应。简短、亲切，像朋友聊天。"
    ),
}


def get_narration_instruction(intention: Optional[str]) -> str:
    """按意图取播报指令，未匹配返回通用指令。"""
    if intention and intention in NARRATION_INSTRUCTIONS:
        return NARRATION_INSTRUCTIONS[intention]
    return "用自然口语给用户汇报结果，简短亲切，像朋友聊天。"


# 进度播报模板（persona × milestone × skill → 短文案，0 延迟）
# milestone:
#   thinking          - 思考中
#   skill_selected    - 选定 skill
#   skill_executing   - skill 执行中（按 agent_name）
#   skill_complete    - skill 完成（按 agent_name）
# skill 通配 "*" 兜底；persona 通配 "*" 兜底
PROGRESS_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "loli_guide": {
        "thinking": {"*": "嗯…让我想想哈～"},
        "skill_selected": {"*": "好嘞，开工！"},
        "skill_executing": {
            "itinerary_planning": "行程我帮你排排看～",
            "place-search": "酒店我找找哈～",
            "hotel_search": "酒店我找找哈～",
            "restaurant_search": "餐厅我看看～",
            "scenic_search": "景点我挑挑～",
            "information_query": "信息我查一下～",
            "rag_knowledge": "知识我翻一下～",
            "expense_tracking": "记账咯～",
            "translation": "翻译中～",
            "train_ticket": "车票我查查～",
            "*": "正在查～",
        },
        "skill_complete": {
            "itinerary_planning": "行程排好啦！",
            "place-search": "找到啦！",
            "hotel_search": "酒店找到啦！",
            "restaurant_search": "餐厅选好啦！",
            "scenic_search": "景点挑好啦！",
            "information_query": "查到了～",
            "rag_knowledge": "找到了～",
            "expense_tracking": "记好啦！",
            "translation": "翻好啦～",
            "train_ticket": "车票查到啦！",
            "*": "搞定一项！",
        },
    },
    # 其他角色用通用模板（"*" persona）
    "*": {
        "thinking": {"*": "正在思考..."},
        "skill_selected": {"*": "开始处理。"},
        "skill_executing": {"*": "正在查询..."},
        "skill_complete": {"*": "完成一项。"},
    },
}


def get_progress_text(
    persona_id: Optional[str],
    milestone: str,
    skill: Optional[str] = None,
) -> Optional[str]:
    """按 persona + milestone + skill 取进度文案。

    查找顺序：persona[ms][skill] → persona[ms][*] → *[ms][skill] → *[ms][*]
    未命中返回 None（调用方决定是否调 LLM 兜底）。
    """
    skill = skill or "*"
    persona_id = persona_id if persona_id in PROGRESS_TEMPLATES else "*"
    persona_tbl = PROGRESS_TEMPLATES.get(persona_id, {})
    ms_tbl = persona_tbl.get(milestone, {})
    if skill in ms_tbl:
        return ms_tbl[skill]
    if "*" in ms_tbl:
        return ms_tbl["*"]
    # 回退到通用 persona
    generic = PROGRESS_TEMPLATES.get("*", {}).get(milestone, {})
    if skill in generic:
        return generic[skill]
    return generic.get("*")


def get_persona_meta() -> list[dict]:
    """返回前端展示用元数据。"""
    return [
        {
            "id": p.id,
            "label": p.label,
            "voice": p.voice,
            "lang": p.lang,
            "emoji": p.emoji,
            "sample_text": p.sample_text,
        }
        for p in PERSONAS
    ]
