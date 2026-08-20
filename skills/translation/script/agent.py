"""
翻译智能体 TranslationAgent
职责：语言翻译，支持多语言互译
API: MyMemory (免费，无需 key)
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
import requests
from urllib.parse import quote

from utils.llm_response import extract_llm_json
from cache.decorators import cached

logger = logging.getLogger(__name__)

LANG_MAP = {
    "中文": "zh", "简体中文": "zh", "汉语": "zh",
    "英文": "en", "英语": "en",
    "日文": "ja", "日语": "ja",
    "韩文": "ko", "韩语": "ko",
    "法文": "fr", "法语": "fr",
    "德文": "de", "德语": "de",
    "西班牙文": "es", "西班牙语": "es",
    "俄文": "ru", "俄语": "ru",
    "泰文": "th", "泰语": "th",
    "越南文": "vi", "越南语": "vi",
    "阿拉伯文": "ar", "阿拉伯语": "ar",
    "葡萄牙文": "pt", "葡萄牙语": "pt",
    "意大利文": "it", "意大利语": "it",
}

LANG_NAMES = {
    "zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文",
    "fr": "法文", "de": "德文", "es": "西班牙文", "ru": "俄文",
    "th": "泰文", "vi": "越南文", "ar": "阿拉伯文", "pt": "葡萄牙文",
    "it": "意大利文",
}

API_BASE = "https://api.mymemory.translated.net/get"


class TranslationAgent(AgentBase):
    """翻译智能体"""

    def __init__(self, name: str = "TranslationAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model

    @cached("translation", ttl=86400)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({"error": "No input"}), role="assistant")

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

        # Use LLM to parse translation intent
        prompt = f"""你是翻译助手，请从用户输入中提取翻译信息。

用户输入: {user_query}

请输出JSON:
{{
  "text_to_translate": "要翻译的文本",
  "source_lang": "源语言代码(如zh/en/ja)",
  "target_lang": "目标语言代码(如zh/en/ja)"
}}

语言代码参考: zh(中文), en(英文), ja(日文), ko(韩文), fr(法文), de(德文), es(西班牙文), ru(俄文), th(泰文), vi(越南文)

如果用户没有指定源语言，请自动检测。
如果用户没有指定目标语言，中文翻译成英文，其他语言翻译成中文。

只输出JSON，不要其他文字。"""

        try:
            response = await self.model([{"role": "user", "content": prompt}])
            parsed = extract_llm_json(response)
        except Exception as e:
            logger.error(f"Translation parsing failed: {e}")
            return Msg(name=self.name, content=json.dumps({
                "action": "error",
                "answer": f"无法理解翻译请求: {str(e)}"
            }, ensure_ascii=False), role="assistant")

        text = parsed.get("text_to_translate", "")
        source_lang = parsed.get("source_lang", "auto")
        target_lang = parsed.get("target_lang", "en")

        if not text:
            return Msg(name=self.name, content=json.dumps({
                "action": "error",
                "answer": "未识别到需要翻译的文本"
            }, ensure_ascii=False), role="assistant")

        # Call MyMemory API
        try:
            result = self._translate(text, source_lang, target_lang)
        except Exception as e:
            logger.error(f"Translation API failed: {e}")
            result = {"action": "error", "answer": f"翻译失败: {str(e)}"}

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    def _translate(self, text: str, source_lang: str, target_lang: str) -> dict:
        """调用 MyMemory API 翻译"""
        langpair = f"{source_lang}|{target_lang}"
        encoded_text = quote(text[:500])  # MyMemory limit
        url = f"{API_BASE}?q={encoded_text}&langpair={quote(langpair)}"

        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        translated = data.get("responseData", {}).get("translatedText", "")
        match_quality = data.get("responseData", {}).get("match", 0)

        if not translated or translated.lower() == text.lower():
            return {
                "action": "error",
                "answer": f"翻译失败，无法翻译该文本"
            }

        source_name = LANG_NAMES.get(source_lang, source_lang)
        target_name = LANG_NAMES.get(target_lang, target_lang)

        return {
            "action": "translate",
            "source_text": text,
            "translated_text": translated,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "confidence": match_quality,
            "answer": f"【{source_name}→{target_name}】\n{translated}",
            "proactive_question": "需要我帮你再翻译一段其他内容吗？",
        }
