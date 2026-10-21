import type { IntentionData, AgentResult, OrchestrationResult } from './types'

interface SSECallbacks {
  onThinking?: (data: { status: string }) => void
  onIntention?: (data: IntentionData) => void
  onDispatching?: (data: { agents: unknown[] }) => void
  onAgentStart?: (data: { agent_name: string; status: string }) => void
  onAgentResult?: (data: AgentResult) => void
  onComplete?: (data: OrchestrationResult) => void
  onError?: (data: { message: string }) => void
  onClarification?: (data: { question: string; missing_info?: string[] }) => void
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
): Promise<void> {
  const controller = new AbortController()
  activeController = controller

  const body = JSON.stringify({ user_id: userId, session_id: sessionId, message })

  let response: Response
  try {
    response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: controller.signal,
    })
  } catch (err) {
    if (controller.signal.aborted) return // user cancelled
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
            if (!eventName) continue
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
            // ignore parse errors
          }
        }
      }
    }

    if (!terminal && !controller.signal.aborted) {
      callbacks.onError?.({ message: '连接提前结束，结果可能不完整，请重试。' })
    }
  } finally {
    reader.releaseLock()
    if (activeController === controller) {
      activeController = null
    }
  }
}

async function fetchJson(url: string, init?: RequestInit) {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json()
}

function userQuery(userId: string, sessionId?: string | null) {
  const params = new URLSearchParams({ user_id: userId })
  if (sessionId) params.set('session_id', sessionId)
  return params.toString()
}

export async function fetchPreferences(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/preferences?${userQuery(userId, sessionId)}`)
}

export async function fetchHistory(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/history?${userQuery(userId, sessionId)}`)
}

export async function fetchContext(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/context?${userQuery(userId, sessionId)}`)
}

export async function fetchExpenses(userId: string, sessionId?: string | null) {
  return fetchJson(`/api/expenses?${userQuery(userId, sessionId)}`)
}

export async function createSession(userId: string) {
  return fetchJson('/api/session/new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
  })
}
