import type { FollowUpSuggestion, SuggestionContext } from './suggestionEngine'

// ── 缓存 ──────────────────────────────────────────────

interface CacheEntry {
  suggestions: FollowUpSuggestion[]
  timestamp: number
}

const cache = new Map<string, CacheEntry>()
const CACHE_TTL = 5 * 60 * 1000 // 5 min

function cacheKey(ctx: SuggestionContext): string {
  const primary = ctx.intention?.intents?.[0]?.type || 'unknown'
  const dest = ctx.intention?.key_entities?.destination || ''
  return `${ctx.userMessage.slice(0, 40)}|${primary}|${dest}`
}

// ── LLM 调用 ──────────────────────────────────────────
// 通过 Vite 环境变量配置 LLM API（复用服务端同一模型）
// VITE_LLM_API_URL  - OpenAI 兼容 API 地址
// VITE_LLM_API_KEY  - API Key
// VITE_LLM_MODEL    - 模型名
// 未配置则自动降级，仅使用规则引擎结果

function buildPrompt(ctx: SuggestionContext): string {
  const intents = ctx.intention?.intents?.map((i) => i.type).join(', ') || '未知'
  const entities = ctx.intention?.key_entities
  const entityParts: string[] = []
  if (entities?.destination) entityParts.push(`目的地: ${entities.destination}`)
  if (entities?.origin) entityParts.push(`出发地: ${entities.origin}`)
  if (entities?.date) entityParts.push(`日期: ${entities.date}`)
  if (entities?.duration) entityParts.push(`天数: ${entities.duration}`)

  const agentNames = ctx.agentResults.map((r) => r.agent_name).join(', ')

  // 拼接已有回答摘要
  const answers: string[] = []
  for (const r of ctx.agentResults) {
    const d = r.data as Record<string, unknown>
    const inner = (d.data || d) as Record<string, unknown>
    const a = inner.answer || inner.content || inner.result || inner.summary || inner.message
    if (a && typeof a === 'string') answers.push(a.slice(0, 100))
  }

  const personaParts: string[] = []
  if (ctx.persona.homeCity) personaParts.push(`常住城市: ${ctx.persona.homeCity}`)
  if (ctx.persona.recentTrips?.length) {
    personaParts.push(`最近行程: ${ctx.persona.recentTrips.map((t) => t.destination).join(', ')}`)
  }

  return `你是旅行助手的追问建议生成器。根据以下上下文，生成 2-3 条用户可能追问的自然语言问题。

## 本轮对话
用户: ${ctx.userMessage}
意图: ${intents}
${entityParts.length > 0 ? `关键实体: ${entityParts.join(', ')}` : ''}
AI 执行了: ${agentNames}
${answers.length > 0 ? `AI 回答摘要: ${answers.join('; ')}` : ''}
${personaParts.length > 0 ? `## 用户画像\n${personaParts.join('\n')}` : ''}

## 特别注意
- 如果用户表达了对某个城市的偏好（如"我喜欢去XX"），优先生成与该城市相关的问题：
  行程规划、交通方式、天气、住宿等，而不是偏好管理类问题
- 追问应自然衔接当前对话，不要跳到无关话题
- 口语化表达：用"怎么去青岛"而不是"查询青岛交通方式"

## 要求
- 每个追问控制在 15 字以内
- 追问用自然口语
- 优先深化追问，其次扩展追问
- 输出 JSON 数组: [{"text": "...", "type": "deepen|explore|action", "icon": "emoji"}]`
}

export async function fetchLLMSuggestions(
  ctx: SuggestionContext,
  existingTexts: Set<string>,
  signal?: AbortSignal,
): Promise<FollowUpSuggestion[]> {
  const apiUrl = import.meta.env.VITE_LLM_API_URL
  const apiKey = import.meta.env.VITE_LLM_API_KEY
  const model = import.meta.env.VITE_LLM_MODEL || 'deepseek-chat'

  // 未配置 LLM API → 自动降级
  if (!apiUrl || !apiKey) return []

  // 检查缓存
  const key = cacheKey(ctx)
  const cached = cache.get(key)
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.suggestions.filter((s) => !existingTexts.has(s.text))
  }

  try {
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: '你是一个追问建议生成器。只输出 JSON 数组，不要输出任何其他内容。' },
          { role: 'user', content: buildPrompt(ctx) },
        ],
        max_tokens: 200,
        temperature: 0.7,
      }),
      signal,
    })

    if (!response.ok) return []

    const data = await response.json()
    const content = data.choices?.[0]?.message?.content || ''
    const suggestions = parseSuggestions(content, existingTexts)

    // 写入缓存
    cache.set(key, { suggestions, timestamp: Date.now() })

    return suggestions
  } catch {
    // 网络错误 / abort — 静默降级
    return []
  }
}

function parseSuggestions(content: string, existingTexts: Set<string>): FollowUpSuggestion[] {
  try {
    // 尝试提取 JSON 数组
    const match = content.match(/\[[\s\S]*\]/)
    if (!match) return []
    const arr = JSON.parse(match[0])
    if (!Array.isArray(arr)) return []

    return arr
      .filter((item: { text?: string }) => item.text && !existingTexts.has(item.text))
      .slice(0, 3)
      .map((item: { text: string; type?: string; icon?: string }, i: number) => ({
        id: `llm_${i}_${Date.now()}`,
        text: item.icon ? `${item.icon} ${item.text}` : item.text,
        query: item.text,
        type: (item.type === 'deepen' || item.type === 'explore' || item.type === 'action'
          ? item.type
          : 'explore') as FollowUpSuggestion['type'],
        source: 'llm' as const,
        icon: item.icon || '💡',
      }))
  } catch {
    return []
  }
}
