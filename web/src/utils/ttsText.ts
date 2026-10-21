import type { AgentResult } from '../api/types'

/** 有些 Agent 的 answer 字段本身就是一段 JSON，取出其中的自然语言。 */
function unwrapAnswer(value: unknown): string {
  if (typeof value !== 'string') return ''
  const text = value.trim()
  if (text.startsWith('{') && text.endsWith('}')) {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>
      for (const key of ['answer', 'response', 'content', 'result', 'message']) {
        const nested = parsed[key]
        if (typeof nested === 'string' && nested.trim()) return nested.trim()
      }
    } catch {
      // not JSON, keep original
    }
  }
  return value
}

/**
 * 从 AgentResult 提取适合朗读的简短文本。
 * 行程规划等长文本只朗读标题 + 概要，避免朗读几千字。
 */
export function extractTTSText(result: AgentResult): string {
  if (result.status === 'error') {
    const errDetail = (result.data as any)?.error || (result.data as any)?.message || ''
    return errDetail ? `${result.agent_name} 执行失败：${errDetail}` : `${result.agent_name} 执行失败`
  }

  const d = (result.data as Record<string, unknown>) || {}
  const inner = (d.data || d) as Record<string, unknown>
  const agent = result.agent_name

  switch (agent) {
    case 'itinerary_planning': {
      const it = (inner.itinerary || inner) as Record<string, unknown>
      const title = (it.title as string) || '行程规划'
      const duration = (it.duration as string) || ''
      const plans = Array.isArray(it.daily_plans) ? it.daily_plans : []
      const complete = inner.planning_complete !== false
      const summary = complete
        ? `已为您规划好${duration || ''}行程：${title}，共 ${plans.length} 天，请查看详情。`
        : `行程规划未完成：${(inner.error as string) || '请补充更多信息'}`
      return summary
    }

    case 'information_query': {
      const results = (inner.results || inner) as Record<string, unknown>
      const summary = (results.summary as string) || (inner.summary as string) || (inner.message as string) || (inner.answer as string)
      return summary as string || ''
    }

    case 'rag_knowledge':
    case 'memory_query':
    case 'visa_info': {
      const answer = inner.answer ?? inner.content ?? inner.result ?? inner.summary
      return unwrapAnswer(answer)
    }

    case 'expense_tracker':
    case 'expense_tracking': {
      const answer = (inner.answer as string) || (inner.message as string)
      if (answer) return answer as string
      const expense = inner.expense as Record<string, unknown> | undefined
      if (expense) {
        const category = expense.category || '其他'
        const amount = expense.amount
        return `已记录${category} ${amount} 元`
      }
      return '费用已记录'
    }

    case 'currency_converter':
    case 'currency_conversion': {
      const answer = (inner.answer as string) || (inner.result as string) || (inner.message as string)
      return answer as string || ''
    }

    case 'preference': {
      const answer = (inner.answer as string) || (inner.message as string)
      return answer as string || '偏好已更新'
    }

    case 'translation': {
      const translated = (inner.translated_text as string) || (inner.translation as string) || (inner.result as string) || (inner.answer as string)
      return translated as string || ''
    }

    case 'event_collection': {
      const summary = (inner.summary as string) || (inner.message as string)
      return summary as string || ''
    }

    case 'hotel_search':
    case 'restaurant_search':
    case 'scenic_search': {
      const results = (inner.results || inner) as Record<string, unknown>
      const summary = (results.summary as string) || (inner.summary as string) || (inner.message as string)
      const count = (results.count as number) ?? (inner.count as number) ?? 0
      if (summary) return summary
      if (count > 0) return `找到 ${count} 条结果，请查看详情`
      return '未找到相关结果'
    }

    case 'train_ticket': {
      const summary = (inner.summary as string) || (inner.message as string)
      return summary as string || ''
    }

    default: {
      // 兜底：尝试常见字段
      const raw = inner.answer ?? inner.content ?? inner.result ?? inner.message ?? inner.summary ?? inner.description ?? inner.text
      return unwrapAnswer(raw)
    }
  }
}

/**
 * 从一组 AgentResult 提取朗读文本，多条用换行分隔。
 * 跳过空文本。
 */
export function extractTTSTexts(results: AgentResult[]): string {
  const parts: string[] = []
  for (const r of results) {
    const text = extractTTSText(r).trim()
    if (text) parts.push(text)
  }
  return parts.join('\n\n')
}
