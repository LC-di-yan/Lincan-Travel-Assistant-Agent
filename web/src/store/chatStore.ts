import { create } from 'zustand'
import type { Message, IntentionData, AgentResult, OrchestrationResult } from '../api/types'
import { abortActiveRequest } from '../api/client'

interface ChatState {
  userId: string
  sessionId: string | null
  messages: Message[]
  isProcessing: boolean
  currentIntention: IntentionData | null
  currentAgents: AgentResult[]
  runningAgents: string[]
  orchestrationResult: OrchestrationResult | null
  thinkingStatus: string

  setUserId: (id: string) => void
  setSessionId: (id: string) => void
  addMessage: (msg: Message) => void
  updateLastAssistant: (patch: Partial<Message>) => void
  setProcessing: (v: boolean) => void
  setCurrentIntention: (d: IntentionData | null) => void
  addAgentResult: (r: AgentResult) => void
  appendAgentResultToMessage: (r: AgentResult) => void
  // 按消息 id 定向更新：慢请求/旧请求的回调只能写它自己那条消息，
  // 不会因为「最后一条 assistant」被换掉而错挂到新气泡上
  patchMessage: (id: string, patch: Partial<Message>) => void
  appendAgentResultById: (id: string, r: AgentResult) => void
  resetAgentResults: () => void
  addRunningAgent: (name: string) => void
  removeRunningAgent: (name: string) => void
  clearRunningAgents: () => void
  setOrchestrationResult: (r: OrchestrationResult | null) => void
  setThinkingStatus: (s: string) => void
  clearChat: () => void
}

let msgCounter = 0
const uid = () => `msg_${++msgCounter}_${Date.now()}`

const initialUserId = localStorage.getItem('aligo_user_id') || 'default_user'

export const useChatStore = create<ChatState>((set) => ({
  userId: initialUserId,
  sessionId: localStorage.getItem('aligo_session_id') || null,
  messages: [],
  isProcessing: false,
  currentIntention: null,
  currentAgents: [],
  runningAgents: [],
  orchestrationResult: null,
  thinkingStatus: '',

  setUserId: (id) => {
    localStorage.setItem('aligo_user_id', id)
    set({ userId: id })
  },
  setSessionId: (id) => {
    if (id) {
      localStorage.setItem('aligo_session_id', id)
    } else {
      localStorage.removeItem('aligo_session_id')
    }
    set({ sessionId: id })
  },

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  updateLastAssistant: (patch) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant') {
          msgs[i] = { ...msgs[i], ...patch }
          break
        }
      }
      return { messages: msgs }
    }),

  setProcessing: (v) => set({ isProcessing: v }),
  setCurrentIntention: (d) => set({ currentIntention: d }),
  addAgentResult: (r) => set((s) => ({ currentAgents: [...s.currentAgents, r] })),
  appendAgentResultToMessage: (r) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant') {
          const existing = msgs[i].agentResults || []
          msgs[i] = { ...msgs[i], agentResults: [...existing, r] }
          break
        }
      }
      return { messages: msgs }
    }),
  resetAgentResults: () => set({ currentAgents: [] }),

  patchMessage: (id, patch) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  appendAgentResultById: (id, r) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, agentResults: [...(m.agentResults || []), r] } : m,
      ),
    })),
  addRunningAgent: (name) => set((s) => ({
    runningAgents: s.runningAgents.includes(name) ? s.runningAgents : [...s.runningAgents, name],
  })),
  removeRunningAgent: (name) => set((s) => ({
    runningAgents: s.runningAgents.filter((n) => n !== name),
  })),
  clearRunningAgents: () => set({ runningAgents: [] }),
  setOrchestrationResult: (r) => set({ orchestrationResult: r }),
  setThinkingStatus: (s) => set({ thinkingStatus: s }),

  clearChat: () => {
    // 先掐掉仍在途的请求：否则旧流会继续回调，把上一轮内容写进新对话
    abortActiveRequest()
    localStorage.removeItem('aligo_session_id')
    set({
      sessionId: null,
      messages: [],
      currentIntention: null,
      currentAgents: [],
      runningAgents: [],
      orchestrationResult: null,
      thinkingStatus: '',
      isProcessing: false,
    })
  },
}))

export { uid }
