import { ensureIdentity } from './client'
import type { AgentResult, Message } from './types'

export interface ConversationSummary {
  id: string
  title: string
  preview: string
  updated_at: string | null
  readonly: boolean
}

export interface ConversationPage {
  items: ConversationSummary[]
  next_before: number | null
}

interface HistoryMessage {
  id: string
  role: Message['role']
  content: string
  timestamp: string | null
  status?: 'complete' | 'clarification' | 'error' | 'interrupted'
  results?: AgentResult[]
}

export interface TranscriptPage {
  id: string
  readonly: boolean
  messages: HistoryMessage[]
  next_before: number | null
}

export const LEGACY_CONVERSATION = '~legacy'
export const CONVERSATIONS_CHANGED = 'conversations-changed'
export function notifyConversationsChanged() {
  window.dispatchEvent(new Event(CONVERSATIONS_CHANGED))
}

export class ConversationError extends Error {
  readonly status: number

  constructor(status: number) {
    super(status === 404 ? '未找到这条聊天记录。'
      : status === 401 ? '会话身份已失效，请刷新页面后重试。'
      : status === 403 ? '请通过安全链接打开聊天记录。'
      : '聊天记录暂时无法读取，请稍后重试。')
    this.status = status
  }
}

async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  await ensureIdentity()
  const response = await fetch(path, { signal, cache: 'no-store', credentials: 'same-origin' })
  if (!response.ok) throw new ConversationError(response.status)
  return response.json()
}

export function listConversations(query: string, before: number | null, signal: AbortSignal) {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  if (before !== null) params.set('before', String(before))
  return request<ConversationPage>(`/api/conversations?${params}`, signal)
}

export function readConversation(id: string, before: number | null, signal: AbortSignal) {
  const path = `/api/conversations/${encodeURIComponent(id)}/messages`
  return request<TranscriptPage>(before === null ? path : `${path}?before=${before}`, signal)
}

export function restoredMessages(page: TranscriptPage): Message[] {
  return page.messages.map((row) => ({
    id: `history_${page.id}_${row.id}`,
    role: row.role,
    content: row.content,
    timestamp: row.timestamp ? Date.parse(row.timestamp) : 0,
    agentResults: row.results,
    historical: true,
    activity: row.role === 'assistant' ? { started: [], schedule: [],
      phase: row.status === 'complete' ? 'finished' : row.status ?? 'archived' } : undefined,
    isError: row.status === 'error',
  }))
}
