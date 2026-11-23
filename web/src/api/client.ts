import type { IntentionData, AgentResult, OrchestrationResult, PublicAgent } from './types'
import type { PlanRef } from './personal'

interface BrowserIdentity { user_id: string }
interface SessionData { user_id: string; session_id: string }
declare global {
  interface Window { __aligoIdentityResponse?: Promise<Response> }
}
let identityRequest: Promise<BrowserIdentity> | null = null
let sessionRequest: Promise<SessionData> | null = null

export function ensureIdentity(): Promise<BrowserIdentity> {
  if (!identityRequest) {
    const boot = typeof window !== 'undefined' ? window.__aligoIdentityResponse : undefined
    if (boot) delete window.__aligoIdentityResponse
    identityRequest = (boot ?? fetch('/api/identity', { method: 'POST', credentials: 'include' }))
      .then(async (response) => {
        if (!response.ok) throw new Error('无法建立安全会话，请刷新后重试')
        return await response.json() as BrowserIdentity
      })
      .catch((error) => { identityRequest = null; throw error })
  }
  return identityRequest
}

interface SSECallbacks {
  onThinking?: (data: { status: string }) => void
  onIntention?: (data: IntentionData) => void
  onDispatching?: (data: { agents: PublicAgent[] }) => void
  onAgentStart?: (data: PublicAgent) => void
  onAgentResult?: (data: AgentResult) => void
  onComplete?: (data: OrchestrationResult) => void
  onError?: (data: { message: string; interrupted?: boolean; history_warning?: string }) => void
  onClarification?: (data: { question: string; missing_info?: string[]; history_warning?: string }) => void
}

let activeController: AbortController | null = null

export function abortActiveRequest() {
  if (activeController) {
    activeController.abort()
    activeController = null
  }
}

export async function sendChatMessage(
  userId: string,
  message: string,
  sessionId: string | null,
  callbacks: SSECallbacks,
  requestId?: string,
  planRef?: PlanRef,
): Promise<void> {
  const controller = new AbortController()
  activeController = controller

  const identity = await ensureIdentity()
  const body = JSON.stringify({
    user_id: identity.user_id,
    session_id: identity.user_id === userId ? sessionId : null,
    message,
    request_id: requestId,
    plan_ref: identity.user_id === userId ? planRef : undefined,
  })

  let response: Response
  try {
    response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: controller.signal,
      credentials: 'include',
    })
  } catch (err) {
    if (controller.signal.aborted) return // 用户已取消
    throw err
  }

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let terminal = false

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith(':')) {
          continue
        } else if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            const eventName = currentEvent
            currentEvent = ''
            if (!eventName || terminal || controller.signal.aborted) continue
            switch (eventName) {
              case 'thinking':
                callbacks.onThinking?.(data)
                break
              case 'intention':
                callbacks.onIntention?.(data)
                break
              case 'dispatching':
                callbacks.onDispatching?.(data)
                break
              case 'agent_start':
                callbacks.onAgentStart?.(data)
                break
              case 'agent_result':
                callbacks.onAgentResult?.(data)
                break
              case 'complete':
                terminal = true
                callbacks.onComplete?.(data)
                break
              case 'error':
                terminal = true
                callbacks.onError?.(data)
                break
              case 'clarification':
                terminal = true
                callbacks.onClarification?.(data)
                break
              case 'ping':
              case 'keepalive':
                break
            }
          } catch {
            // 忽略无法解析的事件
          }
        }
      }
    }

    if (!terminal && !controller.signal.aborted) {
      callbacks.onError?.({ interrupted: true, message: '连接提前结束，结果可能不完整，请重试。' })
    }
  } catch (error) {
    if (!controller.signal.aborted && !terminal) throw error
  } finally {
    reader.releaseLock()
    if (activeController === controller) {
      activeController = null
    }
  }
}

async function fetchJson(url: string, init?: RequestInit) {
  await ensureIdentity()
  const res = await fetch(url, { ...init, credentials: 'include' })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json()
}

async function userQuery(userId: string, sessionId?: string | null) {
  const identity = await ensureIdentity()
  const params = new URLSearchParams({ user_id: identity.user_id })
  if (sessionId && !sessionId.startsWith('~') && userId === identity.user_id) params.set('session_id', sessionId)
  return params.toString()
}

export async function fetchPreferences(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/preferences?${await userQuery(userId, sessionId)}`)
}

export async function fetchHistory(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/history?${await userQuery(userId, sessionId)}`)
}

export async function fetchContext(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/context?${await userQuery(userId, sessionId)}`)
}

export async function fetchExpenses(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/expenses?${await userQuery(userId, sessionId)}`)
}

export async function createSession(): Promise<SessionData> {
  if (!sessionRequest) {
    sessionRequest = ensureIdentity().then((identity) => fetchJson('/api/session/new', {
      method: 'POST',
      signal: AbortSignal.timeout(8000),
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: identity.user_id }),
    })).finally(() => { sessionRequest = null })
  }
  return sessionRequest
}
