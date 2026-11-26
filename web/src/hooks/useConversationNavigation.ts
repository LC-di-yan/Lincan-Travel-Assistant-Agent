import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ConversationError, LEGACY_CONVERSATION, notifyConversationsChanged, readConversation, restoredMessages,
} from '../api/conversations'
import { createSession } from '../api/client'
import { useChatStore } from '../store/chatStore'

const requestTimeout = 8000

export function useConversationNavigation(restoring = false) {
  const [view, setView] = useState({ epoch: 0, nextBefore: null as number | null })
  const [pending, setPending] = useState(restoring)
  const [problem, setProblem] = useState<{ message: string; retry: () => void } | null>(null)
  const [olderBusy, setOlderBusy] = useState(false)
  const [olderError, setOlderError] = useState('')
  const navigation = useRef<AbortController | null>(null)
  const pagination = useRef<AbortController | null>(null)

  useEffect(() => () => {
    navigation.current?.abort()
    pagination.current?.abort()
    navigation.current = null
    pagination.current = null
  }, [])

  const begin = useCallback(() => {
    navigation.current?.abort()
    const controller = new AbortController()
    navigation.current = controller
    setPending(true)
    setProblem(null)
    return controller
  }, [])

  const finish = useCallback((controller: AbortController) => {
    if (navigation.current !== controller) return
    navigation.current = null
    setPending(false)
  }, [])

  const activate = useCallback((id: string, messages: ReturnType<typeof restoredMessages>, before: number | null) => {
    pagination.current?.abort()
    pagination.current = null
    setOlderBusy(false)
    setOlderError('')
    useChatStore.getState().activateConversation(id, messages)
    setView((previous) => ({ epoch: previous.epoch + 1, nextBefore: before }))
    notifyConversationsChanged()
  }, [])

  const open = useCallback(async function openConversation(id: string, restore = false): Promise<boolean> {
    const current = useChatStore.getState()
    if (!restore && !navigation.current && id === current.sessionId && current.messages.length) return true
    const controller = begin()
    const timer = window.setTimeout(() => controller.abort(), requestTimeout)
    try {
      const page = await readConversation(id, null, controller.signal)
      if (navigation.current !== controller) return false
      activate(page.id, restoredMessages(page), page.next_before)
      return true
    } catch (error) {
      if (navigation.current !== controller) return false
      // A session allocated without a first message has nothing to restore.
      if (restore && error instanceof ConversationError && error.status === 404) {
        if (id === LEGACY_CONVERSATION) useChatStore.getState().setSessionId(null)
        return true
      }
      setProblem({
        message: error instanceof ConversationError ? error.message : '聊天记录暂时无法读取，当前对话未切换。',
        retry: () => { void openConversation(id, restore) },
      })
      return false
    } finally {
      window.clearTimeout(timer)
      finish(controller)
    }
  }, [activate, begin, finish])

  const startNew = useCallback(async function newConversation(): Promise<boolean> {
    const controller = begin()
    try {
      const { session_id } = await createSession()
      if (navigation.current !== controller) return false
      const { sessionId, pendingPlan, draftPrompt } = useChatStore.getState()
      activate(session_id, [], null)
      // Personal center may explicitly send a saved plan or query to the composer
      // while an old, read-only archive is open.
      if (sessionId === LEGACY_CONVERSATION) {
        if (pendingPlan) useChatStore.getState().setPendingPlan(pendingPlan)
        if (draftPrompt) useChatStore.getState().setDraftPrompt(draftPrompt)
      }
      return true
    } catch {
      if (navigation.current !== controller) return false
      setProblem({ message: '暂时无法新建对话，当前对话未变更。', retry: () => { void newConversation() } })
      return false
    } finally {
      finish(controller)
    }
  }, [activate, begin, finish])

  const loadOlder = useCallback(async (beforePrepend?: () => void) => {
    const id = useChatStore.getState().sessionId
    if (!id || view.nextBefore === null || pagination.current || navigation.current) return
    const controller = new AbortController()
    pagination.current = controller
    setOlderBusy(true)
    setOlderError('')
    const timer = window.setTimeout(() => controller.abort(), requestTimeout)
    try {
      const page = await readConversation(id, view.nextBefore, controller.signal)
      if (pagination.current !== controller || useChatStore.getState().sessionId !== id) return
      beforePrepend?.()
      useChatStore.getState().prependHistory(id, restoredMessages(page))
      setView((previous) => ({ ...previous, nextBefore: page.next_before }))
    } catch {
      if (pagination.current === controller) setOlderError('暂时无法加载更早的消息，请重试。')
    } finally {
      window.clearTimeout(timer)
      if (pagination.current === controller) {
        pagination.current = null
        setOlderBusy(false)
      }
    }
  }, [view.nextBefore])

  return { view, pending, problem, olderBusy, olderError, open, startNew, loadOlder }
}
