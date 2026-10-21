import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import { Volume2, Square, Loader2 } from 'lucide-react'
import { Markdown } from '../Markdown'
import type { Message } from '../../api/types'
import { ResultDashboard } from '../Results/ResultDashboard'
import { ProactiveQuestion } from './ProactiveQuestion'

const FollowUpSuggestions = lazy(() =>
  import('./FollowUpSuggestions').then((m) => ({ default: m.FollowUpSuggestions })),
)
import { useTTSPlayer } from '../../hooks/useTTSPlayer'
import { useNarrate } from '../../hooks/useNarrate'
import { useChatStore } from '../../store/chatStore'
import { extractTTSTexts } from '../../utils/ttsText'
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
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
      intervalRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startedAt) / 1000))
      }, 1000)
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current)
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }
    return () => {
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
  userMessage = '',
}: {
  msg: Message
  isRunning?: boolean
  isLatest?: boolean
  onSend?: (text: string) => void
  userMessage?: string
}) {
  const isUser = msg.role === 'user'
  const hasResults = Boolean(msg.agentResults && msg.agentResults.length > 0)
  const elapsed = useTimer(msg.startedAt, isRunning)
  const { status, activeMessageId, play, stop } = useTTSPlayer()
  const { narrate } = useNarrate()
  const [generating, setGenerating] = useState(false)
  const ttsBusy = activeMessageId === msg.id && status !== 'idle'
  const time = new Date(msg.timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
  const isError = !isUser && msg.content.trim().startsWith('❌')

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
    if (FAST_PATH.has(intentionType || '')) {
      play(msg.id, fallback, { intention: intentionType })
      return
    }

    setGenerating(true)
    try {
      const narrated = await narrate({
        intention: intentionType,
        resultData: msg.agentResults,
      })
      const textToPlay = narrated || fallback
      if (narrated) {
        useChatStore.getState().patchMessage(msg.id, { narrationText: narrated })
      }
      play(msg.id, textToPlay, { intention: intentionType })
    } finally {
      setGenerating(false)
    }
  }

  const suggestionCtx: SuggestionContext | null =
    isLatest && !isUser && !isRunning && hasResults && onSend
      ? {
          userMessage,
          intention: msg.intention || null,
          agentResults: msg.agentResults || [],
          persona: {},
        }
      : null

  const proactiveQuestion: string = (() => {
    if (!isLatest || isUser || isRunning || !hasResults) return ''
    for (const r of msg.agentResults!) {
      const d = r.data as Record<string, unknown>
      const pq = d.proactive_question
      if (pq && typeof pq === 'string' && pq.trim()) return pq.trim()
      const inner = d.data as Record<string, unknown> | undefined
      if (inner?.proactive_question && typeof inner.proactive_question === 'string' && inner.proactive_question.trim()) {
        return inner.proactive_question.trim()
      }
    }
    return ''
  })()

  if (!isUser && isRunning && !hasResults && !msg.content) return null

  if (isUser) {
    return (
      <div className="px-4 py-2.5 md:px-6" data-message-role="user">
        <div className="mx-auto flex max-w-[760px] justify-end">
          <div className="max-w-[560px]">
            <div className="whitespace-pre-wrap rounded-[2px] border border-rule bg-paper-sunken px-3.5 py-2.5 text-sm leading-7 text-ink">
              {msg.content}
            </div>
            <div className="mt-1 text-right font-mono text-[10px] tabular text-ink-3">{time}</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-2.5 md:px-6" data-message-role="assistant">
      <div className="mx-auto max-w-[760px]">
        <div className="mb-1.5 flex min-h-6 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / 行程文件</span>
          <span className="font-mono text-[10px] tabular text-ink-3">{time}</span>
          {msg.startedAt && (
            <span className="font-mono text-[10px] tabular text-ink-3">
              {isRunning ? '处理中 ' + elapsed + 's' : '用时 ' + elapsed + 's'}
            </span>
          )}
          {!isRunning && !isError && (msg.content || msg.narrationText) && (
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

        {msg.content && !isError && (
          <div className="markdown max-w-[680px]">
            <Markdown>{msg.content}</Markdown>
          </div>
        )}

        {isError && (
          <div className="flex max-w-[680px] items-start gap-3 border border-err/30 bg-error-light px-3 py-2.5">
            <p className="min-w-0 flex-1 text-[12px] leading-5 text-err">
              {msg.content.replace(/^❌\s*/, '')}
            </p>
            {onSend && userMessage && (
              <button
                type="button"
                onClick={() => onSend(userMessage)}
                aria-label="重试上一条消息"
                className="shrink-0 rounded-[2px] border border-err/40 px-2 py-1 text-[10px] font-semibold text-err hover:bg-err/10"
              >
                重试
              </button>
            )}
          </div>
        )}

        {!isRunning && hasResults && (
          <div className="mt-3">
            <ResultDashboard results={msg.agentResults!} />
          </div>
        )}

        {ttsBusy && !isError && (msg.narrationText || msg.content) && (
          <div className="mt-2 flex items-start gap-2 rounded-[2px] border border-rule bg-paper-sunken px-3 py-2 text-[11px] text-ink-2">
            <span className="mt-0.5 flex h-3 items-end gap-0.5 text-accent" aria-hidden="true">
              <span className="h-1.5 w-0.5 animate-pulse bg-current" />
              <span className="h-3 w-0.5 animate-pulse bg-current" />
              <span className="h-2 w-0.5 animate-pulse bg-current" />
            </span>
            <span className="line-clamp-2">{msg.narrationText || msg.content}</span>
          </div>
        )}

        {proactiveQuestion && onSend && (
          <div className="mt-3">
            <ProactiveQuestion question={proactiveQuestion} onSend={onSend} />
          </div>
        )}

        {suggestionCtx && onSend && (
          <Suspense fallback={null}>
            <FollowUpSuggestions context={suggestionCtx} onSend={onSend} />
          </Suspense>
        )}
      </div>
    </div>
  )
}
