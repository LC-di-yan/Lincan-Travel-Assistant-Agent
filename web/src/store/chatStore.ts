import { create } from 'zustand'
import type { Message, IntentionData, AgentResult, OrchestrationResult } from '../api/types'

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

export const useChatStore = create<ChatState>((set) => ({
  userId: 'default_user',
  sessionId: null,
  messages: [],
  isProcessing: false,
  currentIntention: null,
  currentAgents: [],
  runningAgents: [],
  orchestrationResult: null,
  thinkingStatus: '',

  setUserId: (id) => set({ userId: id }),
  setSessionId: (id) => set({ sessionId: id }),

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
  addRunningAgent: (name) => set((s) => ({
    runningAgents: s.runningAgents.includes(name) ? s.runningAgents : [...s.runningAgents, name],
  })),
  removeRunningAgent: (name) => set((s) => ({
    runningAgents: s.runningAgents.filter((n) => n !== name),
  })),
  clearRunningAgents: () => set({ runningAgents: [] }),
  setOrchestrationResult: (r) => set({ orchestrationResult: r }),
  setThinkingStatus: (s) => set({ thinkingStatus: s }),

  clearChat: () =>
    set({
      messages: [],
      currentIntention: null,
      currentAgents: [],
      runningAgents: [],
      orchestrationResult: null,
      thinkingStatus: '',
      isProcessing: false,
    }),
}))

export { uid }
