---
name: translation
description: Use this skill when the user needs translation between languages. Triggers when user says "翻译成英文", "用日语怎么说", "translate to Chinese", "帮我翻译", or any translation request. Uses TranslationAgent with LLM to parse language pairs and MyMemory API for translation.
---

# Translation (翻译助手)

帮助用户在不同语言之间进行翻译，支持中英日韩等多种语言。

## When to Use

- 用户说「翻译成英文」「用日语怎么说」「帮我翻译XX」等
- 需要翻译菜单、路牌、指示牌等旅行中的文字

## Agent

- **TranslationAgent** (`script/agent.py`)
- LLM 解析源语言和目标语言
- MyMemory API 执行翻译（免费，无需 key）
- **异步**：`reply()` 为 `async`，需 `await`

## 返回格式

- `action`: `"translate"` 或 `"error"`
- `source_text`: 原文
- `translated_text`: 译文
- `source_lang`: 源语言
- `target_lang`: 目标语言
- `answer`: 自然语言回答

## 支持语言

- 中文 (zh)、英文 (en)、日文 (ja)、韩文 (ko)
- 法文 (fr)、德文 (de)、西班牙文 (es)、俄文 (ru)
- 泰文 (th)、越南文 (vi)、阿拉伯文 (ar)
