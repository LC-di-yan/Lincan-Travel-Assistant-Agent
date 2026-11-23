import type { Message } from '../api/types'

// Only bind a receipt to an identified option from the immediately preceding
// candidate. A matching option id alone is not a cross-turn identity.
export function selectionSource(message: Message | undefined, text: string, session: string | null) {
  if (!session || message?.role !== 'assistant' || message.historical) return
  const result = message.orchestrationResult
  if (!result?.trip_plan || (result.candidate_session_id && result.candidate_session_id !== session)) return
  const match = /^(?:选择|采用|确认|选)\s*(?:第?\s*([123一二三])\s*(?:个|号)?方案|方案\s*([123一二三]))[。！!]?$/u.exec(text.trim())
  if (!match) return
  const s = match[1] || match[2]
  const number = Number(s) || '一二三'.indexOf(s) + 1
  const items = result.trip_plan.alternatives
  const option = Array.isArray(items) ? items[number - 1] : null
  if (option?.status === 'validated' && typeof option.id === 'string' && option.id)
    return { sourceMessageId: message.id, optionId: option.id, number, session }
}
