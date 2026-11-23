import { create } from 'zustand'
import type { Message } from '../api/types'
import { abortActiveRequest } from '../api/client'
import type { PlanLink } from '../api/personal'

interface ChatState {
  userId: string
  sessionId: string | null
  messages: Message[]
  isProcessing: boolean
  pendingPlan: PlanLink | null
  draftPrompt: string | null

  setUserId: (id: string) => void
  setSessionId: (id: string | null) => void
  addMessage: (msg: Message) => void
  setProcessing: (v: boolean) => void
  // 按消息 id 定向更新：慢请求/旧请求的回调只能写它自己那条消息，
  // 不会因为「最后一条 assistant」被换掉而错挂到新气泡上
  patchMessage: (id: string, patch: Partial<Message>) => void
  setPendingPlan: (link: PlanLink | null) => void
  setDraftPrompt: (value: string | null) => void
  activateConversation: (id: string, messages: Message[]) => void
  prependHistory: (id: string, messages: Message[]) => void
}

let msgCounter = 0
const uid = () => `msg_${++msgCounter}_${Date.now()}`

function rememberSession(id: string | null) {
  if (id) localStorage.setItem('aligo_session_id', id)
  else localStorage.removeItem('aligo_session_id')
}

export const useChatStore = create<ChatState>((set) => ({
  userId: '',
  sessionId: null,
  messages: [],
  isProcessing: false,
  pendingPlan: null,
  draftPrompt: null,

  setUserId: (id) => {
    localStorage.setItem('aligo_user_id', id)
    set({ userId: id })
  },
  setSessionId: (id) => {
    rememberSession(id)
    set({ sessionId: id })
  },

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  setProcessing: (v) => set({ isProcessing: v }),
  patchMessage: (id, patch) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  setPendingPlan: (link) => set({ pendingPlan: link }),
  setDraftPrompt: (value) => set(value ? { draftPrompt: value, pendingPlan: null } : { draftPrompt: null }),

  activateConversation: (id, messages) => {
    // Reset the active view, not the owner's persisted data.
    abortActiveRequest()
    rememberSession(id)
    set({
      sessionId: id,
      messages,
      isProcessing: false,
      pendingPlan: null,
      draftPrompt: null,
    })
  },
  prependHistory: (id, incoming) => set((state) => {
    if (state.sessionId !== id) return state
    const visible = new Set(state.messages.map((row) => row.id))
    return { messages: [...incoming.filter((row) => !visible.has(row.id)), ...state.messages] }
  }),
}))

export { uid }
