import type { AgentResult, Message } from '../api/types'
import { extractTTSText } from './ttsText'
import { asRecord, unwrapResultData } from './resultData'

export type ResultCardKind =
  | 'error' | 'knowledge' | 'information' | 'preference' | 'expense' | 'currency'
  | 'translation' | 'itinerary' | 'trip-plan' | 'event' | 'hotel' | 'restaurant' | 'scenic' | 'train'

export interface ResultPresentation {
  kind: ResultCardKind
  data: Record<string, unknown>
  /** Only exact copies of text owned by this visible card may leave the message body. */
  duplicateTexts: string[]
  supplementalTexts?: string[]
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function answerText(value: unknown): string {
  const valueText = text(value)
  if (!/^[{[]/.test(valueText)) return valueText
  try {
    return readableDetails(JSON.parse(valueText))
  } catch {
    return ''
  }
}

/** Only user-facing prose fields are eligible for the unknown-result fallback. */
function readableDetails(value: unknown, depth = 0): string {
  if (depth > 4 || !value || typeof value !== 'object') return ''
  if (Array.isArray(value)) return [...new Set(value.map((item) => readableDetails(item, depth + 1)).filter(Boolean))].join('\n\n')
  const data = asRecord(value)
  const proseKeys = ['answer', 'response', 'content', 'result', 'message', 'summary', 'description', 'text', 'note', 'hint', 'error', 'details']
  const direct = proseKeys.map((key) => text(data[key])).filter((item) => item && !/^[{[]/.test(item))
  const nested = Object.values(data).map((item) => readableDetails(item, depth + 1)).filter(Boolean)
  return [...new Set([...direct, ...nested])].join('\n\n')
}

function firstText(...values: unknown[]): string {
  return values.map(text).find(Boolean) || ''
}

function readTTS(result: AgentResult): string {
  // Old persisted payloads are not necessarily shaped like today's API types.
  try {
    return text(extractTTSText(result))
  } catch {
    return ''
  }
}

function finiteNumber(value: unknown): number | undefined {
  if (typeof value !== 'number' && !(typeof value === 'string' && value.trim())) return undefined
  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}

function withoutPrefix(value: string, prefixes: string[]): string {
  for (const prefix of prefixes.filter(Boolean).sort((a, b) => b.length - a.length)) {
    if (!value.startsWith(prefix)) continue
    const remaining = value.slice(prefix.length)
    if (!remaining || /^[\s。；;，,]/.test(remaining)) return remaining.replace(/^[\s。；;，,]+/, '')
  }
  return value
}

/** Remove only verified, deterministic receipt facts, not arbitrary prose. */
function currencyNote(data: Record<string, unknown>): string {
  const answer = firstText(data.answer, data.message)
  const number = '([+-]?\\d+(?:\\.\\d+)?)'
  const quote = `参考汇率[:：]\\s*1\\s+([A-Z]{3})\\s*=\\s*${number}\\s+([A-Z]{3})(?:；汇率日期 (\\d{4}-\\d{2}-\\d{2}))?`
  const converted = answer.match(new RegExp(`^${number}\\s+[^=()\\n]+?=\\s*${number}\\s+[^()\\n]+?\\s*\\(${quote}\\)`))
  if (converted && Number(converted[1]) === Number(data.amount) && Number(converted[2]) === Number(data.result) && converted[3] === data.from && Number(converted[4]) === Number(data.rate) && converted[5] === data.to && (!converted[6] || converted[6] === data.rate_date)) {
    return withoutPrefix(answer, [converted[0]])
  }
  const rate = answer.match(new RegExp(`^[^:\\n]+兑[^:\\n]+${quote}`))
  if (rate && rate[1] === data.from && Number(rate[2]) === Number(data.rate) && rate[3] === data.to && (!rate[4] || rate[4] === data.rate_date)) {
    return withoutPrefix(answer, [rate[0]])
  }
  return answer
}

function expenseNote(data: Record<string, unknown>): string {
  const answer = firstText(data.answer, data.message)
  const expense = asRecord(data.expense)
  const summary = asRecord(data.summary)
  const money = (amount: unknown, currency: unknown): string => {
    const number = finiteNumber(amount)
    const code = text(currency) || 'CNY'
    return number === undefined ? '' : (code === 'CNY' ? '¥' : code + ' ') + number.toFixed(2)
  }
  if (data.action === 'record' && finiteNumber(expense.amount) !== undefined) {
    return withoutPrefix(answer, [`已记录：${text(expense.category) || '其他'} - ${text(expense.description)} ${money(expense.amount, expense.currency)}`])
  }
  if (summary.count && finiteNumber(summary.total) !== undefined) {
    const total = `共${summary.count}笔支出，合计`
    const amount = money(summary.total, summary.currency)
    const categories = Object.entries(asRecord(summary.by_category)).sort(([, a], [, b]) => Number(b) - Number(a))
    const categoryLines = categories.map(([category, amount]) => `${category}: ${money(amount, summary.currency)}`)
    return withoutPrefix(answer, [
      total + amount + '\n' + categoryLines.map((line) => '  ' + line).join('\n'),
      total + ' ' + amount, total + amount,
      '按类别：' + categoryLines.join('，'),
    ])
  }
  return answer
}

function preferenceNote(value: string, preferences: Record<string, unknown>[]): string {
  const values = preferences.flatMap((pref) => Array.isArray(pref.value) ? pref.value.map(text) : [text(pref.value)]).filter(Boolean)
  if (values.includes(value) || value === values.join('、') || value === values.join('和')) return ''
  return withoutPrefix(value, [
    '偏好已更新', '偏好已保存', '偏好保存成功', '已更新偏好', '已保存偏好',
    `已记住您喜欢${values.join('和')}`, `已记住您喜欢${values.join('、')}`,
  ])
}

/**
 * A single presentation contract shared by the dashboard and message body.
 * A typed card must have meaningful data; otherwise a readable knowledge card
 * owns the answer instead of rendering a blank or a fabricated zero-value card.
 */
export function getResultPresentation(result: AgentResult): ResultPresentation {
  const data = unwrapResultData(result.data)
  const nested = asRecord(data.results)
  const duplicates = (...values: unknown[]) => [...new Set(values.map(text).filter(Boolean))]
  const card = (kind: ResultCardKind, prepared = data, ...visibleTexts: unknown[]): ResultPresentation => ({
    kind, data: prepared, duplicateTexts: duplicates(...visibleTexts.flatMap((value) => {
      const whole = text(value)
      return [whole, ...whole.replace(/\r\n?/g, '\n').split(/\n[ \t]*\n/)]
    })),
  })
  const rawAnswer = firstText(data.answer, data.content, data.result, data.message, data.summary, data.description, data.text, nested.summary, nested.message)
  const isExpense = ['expense_tracking', 'expense_tracker'].includes(result.agent_name)
  const fallback = (preferred = ''): ResultPresentation => {
    const answer = answerText(preferred || rawAnswer) || readableDetails(data) || '已收到处理结果，暂时没有可展示的详细内容。'
    return card('knowledge', { ...data, answer }, answer, answerText(rawAnswer) === answer || /^[{[]/.test(rawAnswer) ? rawAnswer : '')
  }

  if (result.status === 'error' && !(result.agent_name === 'train_ticket' && data.availability_status)) {
    const detail = answerText(firstText(data.error, data.message, data.answer)) || readableDetails(data)
    if (isExpense) return card('expense', { ...data, action: 'error', answer: detail }, detail, readTTS(result), `${result.agent_name} 执行失败`)
    return card('error', { ...data, error: detail }, detail, readTTS(result), `${result.agent_name} 执行失败`)
  }

  switch (result.agent_name) {
    case 'information_query': {
      const summary = firstText(nested.summary, nested.message, data.summary, data.message, data.answer)
      const meaningful = summary || data.error || nested.error || data.current || nested.current || data.forecast || nested.forecast || data.requested_range || nested.requested_range
      return meaningful ? card('information', data, summary) : fallback()
    }
    case 'rag_knowledge':
    case 'memory_query':
    case 'visa_info':
      return fallback()
    case 'preference': {
      const prefData = asRecord(data.preferences)
      const preferences = Array.isArray(data.preferences) ? data.preferences : prefData.preferences
      const valid = Array.isArray(preferences) && preferences.length > 0 && preferences.every((item) => {
        const pref = asRecord(item)
        return text(pref.type) && (typeof pref.value === 'string' || Array.isArray(pref.value) && pref.value.every((value) => typeof value === 'string'))
      })
      if (!valid || data.action === 'error' || data.success === false) return fallback()
      const summaries = duplicates(data.answer, data.message, data.summary)
      return {
        ...card('preference', { ...data, preferences }, ...summaries, '偏好已更新'),
        supplementalTexts: duplicates(...summaries.map((summary) => preferenceNote(summary, preferences.map(asRecord)))),
      }
    }
    case 'expense_tracker':
    case 'expense_tracking': {
      const prepared = { ...data, answer: expenseNote(data) }
      const expense = asRecord(data.expense)
      const summary = asRecord(data.summary)
      if (data.action === 'error' || data.action === 'unknown') {
        const answer = answerText(rawAnswer)
        return card('expense', { ...data, action: 'error', answer }, answer, rawAnswer)
      }
      // The receipt shows the verified facts removed by expenseNote and its remaining prose.
      const owned = firstText(data.answer, data.message) || readTTS(result)
      return ['preview', 'delete', 'update'].includes(String(data.action)) ||
        data.action === 'record' && (Object.keys(expense).length > 0 || Array.isArray(data.expenses) || prepared.answer) || Object.keys(summary).length > 0 || prepared.answer
        ? card('expense', prepared, owned, prepared.answer)
        : fallback()
    }
    case 'currency_converter':
    case 'currency_conversion': {
      if (data.action === 'error') return card('currency', { ...data, answer: rawAnswer }, rawAnswer)
      const amount = finiteNumber(data.amount)
      const converted = finiteNumber(data.result)
      if (!text(data.from) || !text(data.to) || amount === undefined || converted === undefined) return fallback()
      // currencyNote removes only a verified conversion prefix; all other prose stays in the card.
      return card('currency', { ...data, amount, result: converted, rate: finiteNumber(data.rate) || 0, answer: currencyNote(data) }, firstText(data.answer, data.message), typeof data.result === 'string' ? data.result : '', `${data.amount} ${data.from} 约等于 ${data.result} ${data.to}`)
    }
    case 'translation': {
      const translated = firstText(data.translated_text, data.translation, data.result, data.answer)
      if (data.action === 'error') return card('translation', { ...data, answer: rawAnswer }, rawAnswer)
      return text(data.source_text) && translated
        ? card('translation', { ...data, translated_text: translated }, translated)
        : fallback(translated)
    }
    case 'itinerary_planning': {
      if (Object.keys(asRecord(data.trip_plan)).length) return card('trip-plan', data, rawAnswer)
      const itinerary = Object.keys(asRecord(data.itinerary)).length ? asRecord(data.itinerary) : data
      if (data.planning_complete === false || itinerary.planning_complete === false) {
        const summary = readTTS(result)
        const explanation = answerText(rawAnswer)
        const presentation = fallback(duplicates(summary, explanation && !summary.includes(explanation) ? explanation : '').join('\n\n'))
        return { ...presentation, duplicateTexts: duplicates(...presentation.duplicateTexts, summary, explanation) }
      }
      if (!text(itinerary.title)) {
        return fallback(rawAnswer || firstText(data.error, itinerary.error))
      }
      // The generated title/day-count summary contains only facts this card renders.
      return card('itinerary', data, readTTS({ ...result, data: { ...data, answer: undefined, message: undefined } }))
    }
    case 'event_collection': {
      const summary = firstText(data.summary, data.message)
      return summary || data.origin || data.destination || data.start_date || data.missing_info
        ? card('event', { ...data, summary }, summary)
        : fallback()
    }
    case 'train_ticket': {
      const results = Object.keys(nested).length ? nested : data
      const summary = firstText(data.error, results.summary, results.message, data.summary, data.message, data.answer)
      const oldError = result.status === 'error' && summary ? `train_ticket 执行失败：${summary}` : ''
      return Array.isArray(results.trains) || summary
        ? card('train', { ...data, results: { ...results, summary } }, summary, oldError)
        : fallback()
    }
    case 'hotel_search':
    case 'restaurant_search':
    case 'scenic_search': {
      const kind = result.agent_name === 'hotel_search' ? 'hotel' : result.agent_name === 'restaurant_search' ? 'restaurant' : 'scenic'
      const results = Object.keys(nested).length ? nested : data
      const summary = firstText(results.summary, data.summary, data.message)
      const items = results[kind === 'hotel' ? 'hotels' : kind === 'restaurant' ? 'restaurants' : 'attractions']
      return Array.isArray(items) || summary || results.count !== undefined
        ? card(kind, { ...data, results: { ...results, summary } }, summary, summary ? '' : readTTS({ ...result, data: { ...data, answer: undefined, message: undefined } }))
        : fallback()
    }
    default:
      return fallback()
  }
}

/** Exact paragraph ownership, never fuzzy matching or hiding an entire mixed reply. */
export function getVisibleMessageContent(msg: Message): string {
  if (msg.role === 'user' || msg.isError || !msg.agentResults?.length) return msg.content
  let content = msg.content.replace(/\r\n?/g, '\n').trim()
  const copies = msg.agentResults.flatMap((result) => getResultPresentation(result).duplicateTexts)
    .map((copy) => copy.replace(/\r\n?/g, '\n').trim())
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
  for (const copy of new Set(copies)) {
    const escaped = copy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    content = content.replace(new RegExp(`(^|\\n[ \\t]*\\n)${escaped}(?=$|\\n[ \\t]*\\n)`, 'g'), '$1').trim()
  }
  return content.replace(/\n(?:[ \t]*\n){2,}/g, '\n\n')
}
