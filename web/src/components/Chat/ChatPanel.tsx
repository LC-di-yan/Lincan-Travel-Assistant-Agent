import { useRef, useEffect, useLayoutEffect, useState, useCallback } from 'react'
import { useChatStore } from '../../store/chatStore'
import { sendChatMessage, createSession, abortActiveRequest } from '../../api/client'
import { LEGACY_CONVERSATION, notifyConversationsChanged } from '../../api/conversations'
import { uid } from '../../store/chatStore'
import { MessageBubble } from './MessageBubble'
import { selectionSource } from '../../utils/selectionReceipt'
import { isExpenseCancellation, isExpenseConfirmation } from '../../utils/expenseEvidence'
import { mergeSchedule, mergeResults, publicTask, type TurnActivity } from '../../utils/agentActivity'
import { ActivityAnnouncement } from './RouteStrip'
import { InputBar } from './InputBar'
import { BriefHeading } from './BriefHero'
import { RouteChart } from '../Illustrations/RouteChart'
import { useTTSPlayer } from '../../hooks/useTTSPlayer'
import { useTTSPrefs } from '../../hooks/useTTSPrefs'
import { useNarrate } from '../../hooks/useNarrate'
import { extractTTSTexts } from '../../utils/ttsText'
import type { AgentResult, OrchestrationResult } from '../../api/types'
import type { PlanLink } from '../../api/personal'

// 简单意图：文案短且结构化，直接用 extractTTSTexts，不调 LLM
const FAST_PATH_INTENTS = new Set([
  'expense_tracking',
  'preference',
  'translation',
  'currency_converter',
  'currency_conversion',
])

// 进度播报节流参数
const PROGRESS_MIN_INTERVAL_MS = 5000  // 两次进度播报最小间隔
const PROGRESS_MAX_COUNT = 3           // 单任务最多进度播报次数
const LONG_TASK_THRESHOLD_MS = 4000    // 任务超过 4s 才触发进度播报

// 简单意图不触发进度播报（任务太短）
const PROGRESS_SKIP_INTENTS = new Set([
  'expense_tracking',
  'preference',
  'translation',
  'currency_converter',
  'currency_conversion',
  'memory_query',
])

export function ChatPanel({ readOnly, switching, onStartNew, loadOlder, olderBusy, olderError, reducedMotion, visible }: {
  reducedMotion: boolean
  visible: boolean
  readOnly: boolean
  switching: boolean
  onStartNew: () => void
  loadOlder?: (beforePrepend: () => void) => Promise<void>
  olderBusy: boolean
  olderError: string
}) {
  const messages = useChatStore((s) => s.messages)
  const activeSession = useChatStore((s) => s.sessionId)
  const pendingPlan = useChatStore((s) => s.pendingPlan)
  const isProcessing = useChatStore((s) => s.isProcessing)
  const brief = messages.length === 0 && !switching && !readOnly
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const loadOlderButton = useRef<HTMLButtonElement>(null)
  const anchoredResult = useRef<string | null>(null)
  const olderAnchor = useRef<{ row: HTMLElement; top: number; focus: HTMLElement | null } | null>(null)
  const following = useRef(true)
  const [atBottom, setAtBottom] = useState(true)
  const showJump = !atBottom && messages.length > 0
  const [offline, setOffline] = useState(() => !navigator.onLine)
  // 当前在途请求对应的 AI 消息 id（供「停止生成」精确定位）
  const activeAssistantIdRef = useRef<string | null>(null)
  const { play, stop } = useTTSPlayer()
  const { prefs } = useTTSPrefs()
  const { narrate, narrateProgress } = useNarrate()
  const autoPlayRef = useRef(prefs.autoPlay)
  useEffect(() => { autoPlayRef.current = prefs.autoPlay }, [prefs.autoPlay])
  useEffect(() => () => { activeAssistantIdRef.current = null; stop() }, [stop])

  // 进度播报节流状态（用 ref 避免 re-render）
  const taskStartRef = useRef<number>(0)
  const lastProgressTimeRef = useRef<number>(0)
  const progressInFlightRef = useRef<symbol | null>(null)
  const progressCountRef = useRef<number>(0)
  const completionNarratingRef = useRef<boolean>(false)
  const playedExecutingRef = useRef<Set<string>>(new Set())

  // 触发进度播报的统一入口（带节流）
  const maybePlayProgress = useCallback(async (
    milestone: 'thinking' | 'skill_selected' | 'skill_executing' | 'skill_complete',
    skill?: string,
  ) => {
    if (!autoPlayRef.current) return
    if (completionNarratingRef.current) return
    // 简单意图跳过
    const intentionType = useChatStore.getState().messages.at(-1)?.intention?.intents?.[0]?.type
    if (intentionType && PROGRESS_SKIP_INTENTS.has(intentionType)) return
    // 长任务门控：未达到阈值不播
    if (taskStartRef.current && Date.now() - taskStartRef.current < LONG_TASK_THRESHOLD_MS) return
    // 节流：间隔 + 次数
    const now = Date.now()
    if (now - lastProgressTimeRef.current < PROGRESS_MIN_INTERVAL_MS) return
    if (progressCountRef.current >= PROGRESS_MAX_COUNT) return
    // skill_executing 同一 skill 只播一次
    if (milestone === 'skill_executing' && skill && playedExecutingRef.current.has(skill)) return

    const source = activeAssistantIdRef.current
    if (!source || progressInFlightRef.current) return
    const ticket = Symbol()
    progressInFlightRef.current = ticket
    let text: string | null
    try {
      text = await narrateProgress({ milestone, skill })
    } finally {
      if (progressInFlightRef.current === ticket) progressInFlightRef.current = null
    }
    if (!text) return

    // 再次检查（narrateProgress 期间状态可能变化）
    if (!source || source !== activeAssistantIdRef.current) return
    if (completionNarratingRef.current) return
    if (!autoPlayRef.current || !useChatStore.getState().isProcessing) return

    lastProgressTimeRef.current = now
    progressCountRef.current += 1
    if (milestone === 'skill_executing' && skill) playedExecutingRef.current.add(skill)
    // 用临时 ID 播放，避免和完成播报冲突
    void play(`progress-${Date.now()}`, text, {})
  }, [narrateProgress, play])

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth && !reducedMotion ? 'smooth' : 'auto' })
  }, [reducedMotion])

  const measureBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el?.clientHeight) return null
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    setAtBottom(near)
    return near
  }, [])

  useEffect(() => {
    const pane = scrollRef.current
    const content = contentRef.current
    if (!visible || !pane || !content) return
    // Lazy results and composer resize can change the bottom gap without a scroll event.
    const observer = new ResizeObserver(measureBottom)
    observer.observe(pane)
    observer.observe(content)
    return () => observer.disconnect()
  }, [measureBottom, visible])

  const onScroll = () => {
    const near = measureBottom()
    if (near !== null) following.current = near
  }

  useLayoutEffect(() => {
    if (!visible || messages.length === 0) return
    const anchor = olderAnchor.current
    const pane = scrollRef.current
    olderAnchor.current = null
    if (anchor?.row.isConnected && pane) {
      const top = anchor.row.getBoundingClientRect().top - pane.getBoundingClientRect().top
      pane.scrollTop += top - anchor.top
      if (anchor.focus && (document.activeElement === anchor.focus ||
        (!anchor.focus.isConnected && document.activeElement === document.body))) {
        anchor.row.focus({ preventScroll: true })
      }
      return
    }

    if (!following.current || !pane) return
    const last = messages.at(-1)
    // Follow the first readable result, not the growing bottom of a long reply.
    // Once the reader has landed here, later packets must not move the page.
    if (last?.role === 'assistant' && !last.historical && last.agentResults?.length) {
      if (anchoredResult.current !== last.id) {
        const first = contentRef.current?.lastElementChild?.querySelector('[data-result-stack]')
        if (first) {
          anchoredResult.current = last.id
          const top = first.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop
          pane.scrollTop = Math.min(top - 12, pane.scrollHeight - pane.clientHeight)
        }
      }
      return
    }
    scrollToBottom(false)
  }, [messages, isProcessing, scrollToBottom, visible])

  const handleSend = useCallback(async (text: string, retryId?: string, retryPlan?: PlanLink) => {
    const store = useChatStore.getState()

    if (!navigator.onLine || !text.trim() || switching || store.sessionId === LEGACY_CONVERSATION || store.isProcessing) return

    // Stop any previous stream before starting another turn.
    abortActiveRequest()

    const selection = !retryId && !store.pendingPlan ? selectionSource(store.messages.at(-1), text, store.sessionId) : undefined
    const userMessageId = uid()
    const planLink = retryId ? retryPlan : store.pendingPlan ?? undefined
    const requestId = retryId ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('')
    // 本轮请求专属的 AI 消息 id，所有回调只认这个 id
    const assistantMessageId = uid()

    store.addMessage({
      id: userMessageId,
      role: 'user',
      content: text,
      requestId,
      planLink,
      timestamp: Date.now(),
    })

    let activity: TurnActivity = { phase: 'submitted', schedule: [], started: [] }
    let results: AgentResult[] = []
    const updateActivity = (patch: Partial<TurnActivity>) => {
      activity = { ...activity, ...patch }
      store.patchMessage(assistantMessageId, { activity })
    }

    store.addMessage({
      id: assistantMessageId, activity,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      startedAt: Date.now(),
    })
    activeAssistantIdRef.current = assistantMessageId

    store.setProcessing(true)
    if (!retryId) store.setPendingPlan(null)
    following.current = true

    // 重置进度播报状态
    taskStartRef.current = Date.now()
    lastProgressTimeRef.current = 0
    progressInFlightRef.current = null
    progressCountRef.current = 0
    completionNarratingRef.current = false
    playedExecutingRef.current = new Set()

    const isCurrent = () => activeAssistantIdRef.current === assistantMessageId && useChatStore.getState().messages.some((message) => message.id === assistantMessageId)
    let listed = false
    try {
      let sessionId = store.sessionId
      if (!sessionId) {
        const session = await createSession()
        if (!isCurrent()) return
        sessionId = session.session_id
        store.setSessionId(sessionId)
      }
      await sendChatMessage(store.userId, text, sessionId, {
        onThinking: () => {
          if (!isCurrent()) return
          updateActivity({ phase: 'receiving' })
          if (!listed) {
            listed = true
            notifyConversationsChanged()
          }
        },
        onIntention: (data) => {
          if (!isCurrent()) return
          updateActivity({ phase: 'receiving', schedule: (data.agent_schedule ?? []).map(publicTask) })
          store.patchMessage(assistantMessageId, { intention: data })
          // 意图确定 → skill_selected 进度播报
          if (!data.trip_request) void maybePlayProgress('skill_selected')
        },
        onDispatching: ({ agents }) => {
          if (!isCurrent()) return
          updateActivity({ phase: 'receiving', schedule: mergeSchedule(activity.schedule, (agents ?? []).map(publicTask)) })
        },
        onAgentStart: (data) => {
          if (!isCurrent()) return
          if (!data.node_id || !activity.started.some(row => row.node_id === data.node_id)) {
            updateActivity({ phase: 'receiving', started: [...activity.started, publicTask(data)] })
          }
          // 子 agent 开始 → skill_executing 进度播报
          if (!data.node_id) void maybePlayProgress('skill_executing', data.agent_name)
        },
        onAgentResult: (data) => {
          if (!isCurrent()) return
          if (activity.phase === 'submitted') updateActivity({ phase: 'receiving' })
          results = mergeResults(results, [data])
          store.patchMessage(assistantMessageId, { agentResults: results })
          // 子 agent 完成 → skill_complete 进度播报（仅 success）
          if (data.status === 'success' && !data.node_id) {
            void maybePlayProgress('skill_complete', data.agent_name)
          }
        },
        onComplete: async (data: OrchestrationResult) => {
          if (!isCurrent()) return
          updateActivity({ phase: 'finished' })
          if (selection && selection.optionId === data.selected_proposal && selection.session === useChatStore.getState().sessionId &&
              data.status === 'completed') {
            const { sourceMessageId, optionId, number } = selection
            store.patchMessage(sourceMessageId, { confirmedOptionId: optionId })
            store.patchMessage(assistantMessageId, { selectionReceipt: { sourceMessageId, optionId, number } })
          }
          results = mergeResults(results, data.results, true)
          store.setProcessing(false)
          store.patchMessage(assistantMessageId, {
            agentResults: results,
            orchestrationResult: data,
            historyWarning: data.history_warning,
          })
          notifyConversationsChanged()
          const fallbackText = data.answer?.trim() || extractTTSTexts(results)
          if (fallbackText) {
            store.patchMessage(assistantMessageId, { content: fallbackText })
          }
          // 费用记录成功后通知侧边栏刷新
          for (const r of data.results) {
            if (['expense_tracking', 'expense_tracker'].includes(r.agent_name) && r.status === 'success'
              && ['record', 'delete', 'update'].includes(String(r.data.action))) {
              window.dispatchEvent(new CustomEvent('expense-updated'))
            }
            if (r.agent_name === 'preference' && r.status === 'success') {
              window.dispatchEvent(new CustomEvent('preference-updated'))
            }
          }
          // 自动朗读
          if (!autoPlayRef.current || !fallbackText) return

          const intentionType = data.intention?.intents?.[0]?.type
          // 用本轮请求自己的消息 id，不再按「最后一条 assistant」猜
          const assistantMsgId = assistantMessageId

          // 标记完成播报进行中（阻止进度播报抢占）
          completionNarratingRef.current = true

          // 简单意图走快路径（不调 LLM）；复杂意图调 narrate，失败回退 fallbackText
          let textToPlay = fallbackText
          if (results.length && !data.trip_plan && data.status !== 'cancelled' && !data.selected_proposal && !FAST_PATH_INTENTS.has(intentionType || '')) {
            const narrated = await narrate({
              intention: intentionType,
              resultData: results,
            })
            if (narrated && isCurrent()) {
              textToPlay = narrated
              // 存到 message，手动播放按钮可复用
              store.patchMessage(assistantMessageId, { narrationText: narrated })
            }
          }
          if (isCurrent() && autoPlayRef.current) void play(assistantMsgId, textToPlay, { intention: intentionType })
        },
        onClarification: (data) => {
          if (!isCurrent()) return
          store.patchMessage(assistantMessageId, { content: data.question, historyWarning: data.history_warning })
          updateActivity({ phase: 'clarification' }); store.setProcessing(false)
          notifyConversationsChanged()
        },
        onError: (data) => {
          if (!isCurrent()) return
          updateActivity({ phase: data.interrupted ? 'interrupted' : 'error' })
          store.setProcessing(false)
          store.patchMessage(assistantMessageId, {
            content: String(data.message ?? '处理失败'), isError: true, historyWarning: data.history_warning,
          })
          notifyConversationsChanged()
        },
      }, requestId, planLink?.ref)
    } catch (err) {
      // Session creation can reject after the user has already cancelled this turn.
      if (isCurrent()) {
        updateActivity({ phase: activity.phase === 'receiving' ? 'interrupted' : 'error' })
        store.patchMessage(assistantMessageId, {
          content: '连接失败: ' + (err instanceof Error ? err.message : String(err)),
          isError: true,
        })
      }
    } finally {
      if (isCurrent()) {
        store.setProcessing(false)
        if (['receiving', 'submitted'].includes(activity.phase)) {
          updateActivity({ phase: 'interrupted' })
          store.patchMessage(assistantMessageId, { content: '连接中断，未收到完整回复。', isError: true })
        }
      }
    }
  }, [maybePlayProgress, narrate, play, switching])

  useEffect(() => {
    const onOnline = () => setOffline(false)
    const onOffline = () => setOffline(true)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  const handleCancel = () => {
    const store = useChatStore.getState()
    if (!store.isProcessing) return
    abortActiveRequest()
    stop()
    store.setProcessing(false)
    const msg = store.messages.find(row => row.id === activeAssistantIdRef.current)
    if (msg?.activity) store.patchMessage(msg.id, { activity: { ...msg.activity, phase: 'cancelled' },
      content: msg.intention?.trip_request ? '本轮查询已取消；已收到的部分结果仍可查看。' : '已停止生成',
    })
    activeAssistantIdRef.current = null
    notifyConversationsChanged()
  }

  const handleLoadOlder = () => {
    if (olderBusy || switching) return
    void loadOlder?.(() => {
      const pane = scrollRef.current
      if (!pane?.clientHeight) return
      const top = pane.getBoundingClientRect().top
      const row = Array.from(contentRef.current?.children ?? []).find(
        (element): element is HTMLElement => element instanceof HTMLElement && element.getBoundingClientRect().bottom > top,
      )
      if (row) olderAnchor.current = {
        row, top: row.getBoundingClientRect().top - top,
        focus: document.activeElement === loadOlderButton.current ? loadOlderButton.current : null,
      }
    })
  }

  return (
    <main className="flight-shell" aria-label="差旅航图台"><div className={brief ? 'deck-layout brief-mode' : 'deck-layout chat-mode'}>
      {brief && <BriefHeading />}
      {brief && <RouteChart />}
      <div className="message-pane" hidden={brief}>
        <div
          ref={scrollRef}
          onScroll={onScroll}
          role="log"
          aria-label="对话消息"
          aria-live={visible && !messages.at(-1)?.historical ? 'polite' : 'off'}
          /* 流式生成期间置 busy：读屏软件等生成结束再整段播报，
             避免逐 token 朗读造成噪音风暴 */
          aria-busy={isProcessing}
          tabIndex={-1}
          className="flex-1 overflow-y-auto py-2"
        >
          {loadOlder && (
            <div className="px-4 py-1 text-center">
              <button ref={loadOlderButton} type="button" onClick={handleLoadOlder} aria-disabled={olderBusy || switching}
                className="min-h-11 rounded-[2px] px-3 text-xs font-medium text-accent underline hover:bg-paper-sunken aria-disabled:opacity-50">
                {olderBusy ? '正在加载…' : olderError || '加载更早的消息'}
              </button>
            </div>
          )}
          <div ref={contentRef}>{messages.map((msg, i) => {
            const isLastAssistant =
              msg.role === 'assistant' &&
              i === messages.length - 1 &&
              isProcessing
            let userMessage: typeof msg | undefined
            if (msg.role === 'assistant') {
              for (let j = i - 1; j >= 0; j--) {
                if (messages[j].role === 'user') {
                  userMessage = messages[j]
                  break
                }
              }
            }
            const next = messages[i + 1]
            const reply = messages[i + 2]
            const pendingExpense = msg.role === 'assistant' && !msg.historical && isProcessing &&
              next?.role === 'user' && reply?.role === 'assistant' && i + 2 === messages.length - 1 &&
              (isExpenseConfirmation(next.content) || isExpenseCancellation(next.content))
              ? next.content : undefined
            const requested = next?.role === 'user' && !next.planLink
              ? selectionSource(msg, next.content, activeSession)
              : undefined
            const proposalRequestState = requested && reply?.role === 'assistant' &&
                reply.selectionReceipt?.sourceMessageId !== msg.id
              ? isProcessing && i + 2 === messages.length - 1 ? 'pending' : 'unconfirmed'
              : undefined
            return (
              <MessageBubble
                key={msg.id}
                msg={msg}
                isRunning={isLastAssistant}
                isLatest={!msg.historical && i === messages.length - 1 && !isProcessing}
                proposalRequestState={proposalRequestState}
                pendingExpense={pendingExpense}
                canSelectProposal={!!activeSession && !pendingPlan}
                onSend={msg.historical || switching ? undefined : handleSend}
                userMessage={userMessage?.content}
                onRetry={!msg.historical && !switching && userMessage ? () => handleSend(userMessage.content, userMessage.requestId, userMessage.planLink) : undefined}
              />
            )
          })}</div>

        </div>

        {showJump && (
          <button
            type="button"
            onClick={event => {
              if (event.detail === 0) scrollRef.current?.focus({ preventScroll: true })
              scrollToBottom(true)
            }}
            className="absolute bottom-3 left-1/2 min-h-11 -translate-x-1/2 rounded-[2px] border border-rule-strong bg-paper-raised px-3 py-1.5 text-[11px] text-ink shadow-sm hover:bg-paper-sunken"
          >
            回到底部 ↓
          </button>
        )}
      </div>

      {readOnly
        ? <div className="flex flex-wrap items-center justify-between gap-x-3 border-t border-rule bg-paper-sunken px-4 py-2 text-sm text-ink-2">
            <span>早期未分开保存的记录仅供查看。新建对话可继续使用。</span>
            <button type="button" onClick={onStartNew} disabled={switching}
              className="min-h-11 px-2 font-semibold text-accent hover:bg-paper disabled:opacity-50">新建对话</button>
          </div>
        : <InputBar onSend={handleSend} onCancel={handleCancel} disabled={isProcessing} blocked={switching}
            brief={brief} visible={visible} offline={offline} examples={!pendingPlan}
            notice={pendingPlan && <div role="status" className="plan-notice">
              <span>将基于「{pendingPlan.title}」第 {pendingPlan.ref.version} 版调整。请描述想改什么。</span>
              <button type="button" onClick={() => useChatStore.getState().setPendingPlan(null)}>取消引用</button>
            </div>} />}
    </div><ActivityAnnouncement /></main>
  )
}
