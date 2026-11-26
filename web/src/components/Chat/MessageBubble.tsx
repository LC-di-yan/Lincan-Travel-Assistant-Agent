import { useState, useEffect, useRef, lazy } from 'react'
import { Volume2, Square, Loader2, TriangleAlert } from 'lucide-react'
import { RouteStrip } from './RouteStrip'
import { Markdown } from '../Markdown'
import type { Message } from '../../api/types'
import { ResultDashboard } from '../Results/ResultDashboard'
import { ProactiveQuestion } from './ProactiveQuestion'

const FollowUpSuggestions = lazy(() =>
  import('./FollowUpSuggestions').then((m) => ({ default: m.FollowUpSuggestions })),
)
const SaveCandidate = lazy(() => import('../Personal/SaveCandidate'))
import { useTTSPlayer } from '../../hooks/useTTSPlayer'
import { DeferredRegion } from '../Layout/DeferredRegion'
import { useNarrate } from '../../hooks/useNarrate'
import { useChatStore } from '../../store/chatStore'
import { extractTTSTexts } from '../../utils/ttsText'
import { getVisibleMessageContent } from '../../utils/resultPresentation'
import { asRecord, unwrapResultData } from '../../utils/resultData'
import { expenseCancellation, isCompactExpense, isExpenseCancellation, isExpenseConfirmation } from '../../utils/expenseEvidence'
import type { ProposalActions } from '../Results/TripPlanCard'
import type { SuggestionContext } from '../../api/suggestionEngine'

const FAST_PATH = new Set([
  'expense_tracking',
  'preference',
  'translation',
  'currency_converter',
  'currency_conversion',
])

function useTimer(startedAt: number | undefined, isRunning: boolean): number {
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!startedAt) return
    if (isRunning) {
      intervalRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startedAt) / 1000))
      }, 1000)
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
    const frame = requestAnimationFrame(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)))
    return () => {
      cancelAnimationFrame(frame)
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [startedAt, isRunning])

  return elapsed
}

export function MessageBubble({
  msg,
  isRunning = false,
  isLatest = false,
  onSend,
  onRetry,
  proposalRequestState,
  pendingExpense,
  canSelectProposal,
  userMessage = '',
}: {
  msg: Message
  isRunning?: boolean
  isLatest?: boolean
  onSend?: (text: string) => void
  onRetry?: () => void
  proposalRequestState?: ProposalActions['requestState']
  pendingExpense?: string
  canSelectProposal?: boolean
  userMessage?: string
}) {
  const isUser = msg.role === 'user'
  const hasResults = Boolean(msg.agentResults && msg.agentResults.length > 0)
  const candidate = !isRunning && msg.orchestrationResult?.candidate_ref && msg.orchestrationResult
  const savePanelId = candidate ? `save-candidate-${msg.id}` : undefined
  const plan = msg.orchestrationResult?.trip_plan
  const elapsed = useTimer(msg.startedAt, isRunning)
  const { status, activeMessageId, play, stop } = useTTSPlayer()
  const { narrate } = useNarrate()
  const [generating, setGenerating] = useState(false)
  const ttsBusy = activeMessageId === msg.id && status !== 'idle'
  const time = msg.timestamp > 0 ? new Date(msg.timestamp).toLocaleString('zh-CN', {
    ...(msg.historical ? { month: 'numeric', day: 'numeric' } : {}),
    hour: '2-digit', minute: '2-digit',
  }) : ''
  const isError = !isUser && msg.isError === true
  const isConfirmationInput = isUser && isExpenseConfirmation(msg.content)
  const isCancellationInput = isUser && isExpenseCancellation(msg.content)
  const visibleContent = isConfirmationInput ? '确认费用操作' : isCancellationInput ? '取消费用操作' : getVisibleMessageContent(msg)
  const onlyCompactExpense = msg.agentResults?.length === 1 && ['expense_tracking', 'expense_tracker'].includes(msg.agentResults[0].agent_name)
    && isCompactExpense(unwrapResultData(msg.agentResults[0].data))
  const speechText = msg.narrationText || msg.content || (msg.agentResults ? extractTTSTexts(msg.agentResults) : '')

  const handlePlay = async () => {
    if (ttsBusy) {
      stop()
      return
    }
    if (generating) return

    if (msg.narrationText) {
      play(msg.id, msg.narrationText, { intention: msg.intention?.intents?.[0]?.type })
      return
    }

    const fallback = msg.content || (msg.agentResults ? extractTTSTexts(msg.agentResults) : '')
    if (!fallback) return

    const intentionType = msg.intention?.intents?.[0]?.type
    if (!hasResults || msg.historical || msg.intention?.trip_request || FAST_PATH.has(intentionType || '')) {
      play(msg.id, fallback, { intention: intentionType })
      return
    }

    setGenerating(true)
    try {
      const narrated = await narrate({
        intention: intentionType,
        resultData: msg.agentResults,
      })
      if (!useChatStore.getState().messages.some((row) => row.id === msg.id)) return
      const textToPlay = narrated || fallback
      if (narrated) {
        useChatStore.getState().patchMessage(msg.id, { narrationText: narrated })
      }
      play(msg.id, textToPlay, { intention: intentionType })
    } finally {
      setGenerating(false)
    }
  }

  const confirmation = isLatest && !isUser && !isRunning && !msg.historical && onSend
    ? msg.agentResults?.flatMap((result) => {
      if (result.status !== 'success' || !['expense_tracking', 'expense_tracker'].includes(result.agent_name)) return []
      const data = unwrapResultData(result.data)
      return data.action === 'preview' && isExpenseConfirmation(data.confirmation_command) ? [data.confirmation_command] : []
    })[0]
    : undefined
  const freshExpenseReceipt = isLatest && !isRunning && !msg.historical &&
    msg.orchestrationResult?.status === 'completed' && isExpenseConfirmation(userMessage)
  const successfulResults = msg.agentResults?.filter((result) => result.status === 'success') ?? []
  const suggestionCtx: SuggestionContext | null =
    isLatest && !isUser && !isRunning && successfulResults.length > 0 && onSend && !confirmation && !onlyCompactExpense
      ? {
          userMessage,
          intention: msg.intention || null,
          agentResults: successfulResults,
          persona: {},
        }
      : null

  const proactiveQuestion: string = (() => {
    if (!isLatest || isUser || isRunning || !hasResults) return ''
    for (const r of successfulResults) {
      const d = unwrapResultData(r.data)
      const pq = d.proactive_question
      if (pq && typeof pq === 'string' && pq.trim()) return pq.trim()
      const inner = d.data as Record<string, unknown> | undefined
      if (inner?.proactive_question && typeof inner.proactive_question === 'string' && inner.proactive_question.trim()) {
        return inner.proactive_question.trim()
      }
    }
    return ''
  })()

  if (!isUser && isRunning && !msg.activity && !hasResults && !msg.content) return null

  if (isUser) {
    return (
      <div className="px-4 py-2.5 md:px-6" data-message-role="user" data-message-id={msg.id} tabIndex={-1}>
        <div className="mx-auto flex max-w-[760px] justify-end">
          <div className="max-w-[560px]">
            <div className="whitespace-pre-wrap rounded-[2px] border border-rule bg-paper-sunken px-3.5 py-2.5 text-sm leading-7 text-ink [overflow-wrap:anywhere]">
              {visibleContent}
            </div>
            <div className="mt-1 text-right font-mono text-[10px] tabular text-ink-3">{time}</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-2.5 md:px-6" data-message-role="assistant" data-message-id={msg.id} tabIndex={-1}>
      <div className="mx-auto max-w-[760px]">
        <div className="message-meta mb-1.5 flex min-h-7 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / 行程文件</span>
          <span className="font-mono text-[10px] tabular text-ink-3">{time}</span>
          {msg.startedAt && (
            <span className="font-mono text-[10px] tabular text-ink-3">
              {isRunning ? '处理中 ' + elapsed + 's' : '用时 ' + elapsed + 's'}
            </span>
          )}
          {!isRunning && !isError && speechText && (
            <button
              type="button"
              onClick={handlePlay}
              aria-label={ttsBusy ? '停止朗读' : '朗读这条回复'}
              title={ttsBusy ? '停止朗读' : '朗读'}
              className="ml-auto flex h-7 items-center gap-1 rounded-[2px] px-1.5 text-[10px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
            >
              {generating ? (
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              ) : ttsBusy ? (
                <Square size={10} fill="currentColor" aria-hidden="true" />
              ) : (
                <Volume2 size={12} aria-hidden="true" />
              )}
              <span>{ttsBusy ? '停止' : '朗读'}</span>
            </button>
          )}
        </div>

        {msg.activity && !onlyCompactExpense && <div className="mb-2"><RouteStrip message={msg} current={isRunning || isLatest} /></div>}
        {visibleContent && !isError && (
          <div className="markdown assistant-prose max-w-[680px]">
            <Markdown>{visibleContent}</Markdown>
          </div>
        )}

        {isError && (
          <div
            role="alert"
            className="flex max-w-[680px] items-start gap-2.5 rounded-[2px] border border-err/30 bg-error-light px-3 py-2.5"
          >
            <TriangleAlert size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-err" aria-hidden="true" />
            <p className="min-w-0 flex-1 text-[12px] leading-5 text-err [overflow-wrap:anywhere]">
              {msg.content}
            </p>
            {(onRetry || (onSend && userMessage)) && (
              <button
                type="button"
                onClick={onRetry ?? (() => onSend?.(userMessage))}
                aria-label="重试上一条消息"
                className="shrink-0 rounded-[2px] border border-err/40 px-2 py-1 text-[10px] font-semibold text-err hover:bg-err/10"
              >
                重试
              </button>
            )}
          </div>
        )}

        {hasResults && (
          <div className="mt-3" data-result-stack data-first-display={!msg.historical}>
            {msg.historical && <p className="mb-1 text-[11px] text-ink-3">历史结果 · 显示当时的信息</p>}
            <ResultDashboard results={msg.agentResults!} expense={{
              confirmation: confirmation && onSend ? {
                command: confirmation, submit: () => onSend(confirmation), cancel: () => onSend(expenseCancellation(confirmation)),
              } : undefined,
              pending: pendingExpense,
              fresh: freshExpenseReceipt,
            }} proposal={{
              historical: msg.historical,
              requestState: proposalRequestState,
              confirmedOptionId: msg.confirmedOptionId,
              savePanelId,
              onSelect: canSelectProposal && isLatest && !isRunning && plan && onSend ? (index, optionId) => {
                const item = Array.isArray(plan.alternatives) && asRecord(plan.alternatives[index - 1])
                if (item && item.id === optionId && item.status === 'validated') onSend(`选择方案${index}`)
              } : undefined,
            }} />
          </div>
        )}

        {msg.historyWarning && <p role="status" className="mt-2 border-l-2 border-warn px-3 text-xs text-ink-2">{msg.historyWarning}</p>}

        {candidate && (
          <DeferredRegion label="保存行程草稿" fallback={null}
            failure={<p id={savePanelId} tabIndex={-1} role="alert" className="mt-3 text-sm text-ink-2">
              保存草稿入口暂时无法加载。可继续阅读方案，或刷新页面后再试。
            </p>}>
            <SaveCandidate id={savePanelId} result={candidate} confirmedOptionId={msg.confirmedOptionId} />
          </DeferredRegion>
        )}

        {ttsBusy && !isError && speechText && (
          <div className="mt-2 flex items-start gap-2 rounded-[2px] border border-rule bg-paper-sunken px-3 py-2 text-[11px] text-ink-2">
            <span className="mt-0.5 flex h-3 items-end gap-0.5 text-accent" aria-hidden="true">
              <span className="h-1.5 w-0.5 animate-pulse bg-current" />
              <span className="h-3 w-0.5 animate-pulse bg-current" />
              <span className="h-2 w-0.5 animate-pulse bg-current" />
            </span>
            <span>正在朗读这条回复</span>
          </div>
        )}

        {proactiveQuestion && (
          <div className="mt-3">
            <ProactiveQuestion question={proactiveQuestion} />
          </div>
        )}

        {suggestionCtx && onSend && (
          <DeferredRegion label="追问建议" fallback={null} failure={null}>
            <FollowUpSuggestions context={suggestionCtx} onSend={onSend} />
          </DeferredRegion>
        )}
      </div>
    </div>
  )
}
