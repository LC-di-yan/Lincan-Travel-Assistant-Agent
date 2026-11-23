import type { AgentResult } from '../api/types'
import { asRecord, unwrapResultData } from './resultData'

function firstText(...values: unknown[]): string {
  return values.find((value) => typeof value === 'string' && value.trim()) as string || ''
}

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
    const detail = unwrapResultData(result.data)
    const errDetail = firstText(detail.error, detail.message, detail.answer)
    if (result.agent_name === 'train_ticket' && detail.availability_status) {
      return errDetail || firstText(asRecord(detail.results).message, asRecord(detail.results).summary) || '铁路数据暂时不可用。'
    }
    return errDetail ? `${result.agent_name} 执行失败：${errDetail}` : `${result.agent_name} 执行失败`
  }

  const inner = unwrapResultData(result.data)
  const agent = result.agent_name

  switch (agent) {
    case 'itinerary_planning': {
      const it = inner.itinerary ? asRecord(inner.itinerary) : inner
      const title = firstText(it.title)
      const duration = firstText(it.duration)
      const plans = Array.isArray(it.daily_plans) ? it.daily_plans : []
      const complete = inner.planning_complete !== false && it.planning_complete !== false
      if (complete && !title) return firstText(inner.answer, inner.message, inner.error, it.error) || '行程结果尚不完整，请补充更多信息。'
      const summary = complete
        ? `已为您规划好${duration || ''}行程：${title}，共 ${plans.length} 天，请查看详情。`
        : `行程规划未完成：${firstText(inner.error, it.error) || '请补充更多信息'}`
      return summary
    }

    case 'information_query': {
      const results = inner.results ? asRecord(inner.results) : inner
      return firstText(results.summary, results.message, inner.summary, inner.message, inner.answer)
    }

    case 'rag_knowledge':
    case 'memory_query':
    case 'visa_info': {
      const answer = firstText(inner.answer, inner.content, inner.result, inner.message, inner.summary)
      return unwrapAnswer(answer)
    }

    case 'expense_tracker':
    case 'expense_tracking': {
      const answer = firstText(inner.answer, inner.message)
      if (answer) return answer
      const expense = asRecord(inner.expense)
      if (Object.keys(expense).length) {
        const category = expense.category || '其他'
        const amount = expense.amount
        return `已记录${category} ${amount} 元`
      }
      return '费用已记录'
    }

    case 'currency_converter':
    case 'currency_conversion': {
      const answer = firstText(inner.answer, inner.result, inner.message)
      if (answer) return answer
      if (typeof inner.amount === 'number' && typeof inner.result === 'number' && firstText(inner.from) && firstText(inner.to)) {
        return `${inner.amount} ${inner.from} 约等于 ${inner.result} ${inner.to}`
      }
      return ''
    }

    case 'preference': {
      return firstText(inner.answer, inner.message) || '偏好已更新'
    }

    case 'translation': {
      return firstText(inner.translated_text, inner.translation, inner.result, inner.answer)
    }

    case 'event_collection': {
      return firstText(inner.summary, inner.message)
    }

    case 'hotel_search':
    case 'restaurant_search':
    case 'scenic_search': {
      const results = inner.results ? asRecord(inner.results) : inner
      const summary = firstText(results.summary, inner.summary, inner.message)
      const count = (results.count as number) ?? (inner.count as number) ?? 0
      if (summary) return summary
      if (count > 0) return `找到 ${count} 条结果，请查看详情`
      return '未找到相关结果'
    }

    case 'train_ticket': {
      return firstText(asRecord(inner.results).summary, inner.summary, inner.message, inner.answer)
    }

    default: {
      // 兜底：尝试常见字段
      const raw = firstText(inner.answer, inner.content, inner.result, inner.message, inner.summary, inner.description, inner.text)
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
