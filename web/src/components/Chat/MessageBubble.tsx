import { useState, useEffect, useRef } from 'react'

import ReactMarkdown from 'react-markdown'
import type { Message } from '../../api/types'
import { ResultDashboard } from '../Results/ResultDashboard'
import { ProactiveQuestion } from './ProactiveQuestion'
import { FollowUpSuggestions } from './FollowUpSuggestions'
import type { SuggestionContext } from '../../api/suggestionEngine'

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

export function MessageBubble({ msg, isRunning = false, onSend, userMessage = '' }: { msg: Message; isRunning?: boolean; onSend?: (text: string) => void; userMessage?: string }) {
  const isUser = msg.role === 'user'
  const hasResults = msg.agentResults && msg.agentResults.length > 0
  const elapsed = useTimer(msg.startedAt, isRunning)

  const suggestionCtx: SuggestionContext | null = (!isUser && !isRunning && hasResults && onSend)
    ? {
        userMessage,
        intention: msg.intention || null,
        agentResults: msg.agentResults || [],
        persona: {},
      }
    : null

  // 从 agentResults 中提取主动反问
  const proactiveQuestion: string = (() => {
    if (isUser || isRunning || !hasResults) return ''
    for (const r of msg.agentResults!) {
      const d = r.data as Record<string, unknown>
      // 顶层 proactive_question
      const pq = d.proactive_question
      if (pq && typeof pq === 'string' && pq.trim()) return pq.trim()
      // 嵌套 data.proactive_question
      const inner = d.data as Record<string, unknown> | undefined
      if (inner?.proactive_question && typeof inner.proactive_question === 'string' && inner.proactive_question.trim()) {
        return inner.proactive_question.trim()
      }
    }
    return ''
  })()

  return (
    <div className={`flex gap-3 px-5 py-3 animate-bubble-in ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className="w-[53px] h-[53px] rounded-full flex items-center justify-center flex-shrink-0 overflow-hidden ring-2 ring-white/15"
        style={
          isUser
            ? {
                background: 'linear-gradient(135deg, var(--accent), #5a9cf7)',
              }
            : {
                background: 'linear-gradient(135deg, var(--accent), #8b5cf6)',
              }
        }
      >
        {isUser ? <img src="/images/user.png" alt="User" className="w-full h-full object-cover" /> : <img src="/images/logo.png" alt="AI" className="w-full h-full object-cover" />}
      </div>

      <div className={`max-w-[80%] ${isUser ? 'text-right' : ''}`}>
        {isUser ? (
          <div
            className="inline-block px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm"
            style={{
              background: 'linear-gradient(135deg, var(--accent), #5a9cf7)',
              color: 'white',
              boxShadow: '0 2px 8px rgba(79, 142, 247, 0.25)',
            }}
          >
            {msg.content}
          </div>
        ) : (
          <div className="space-y-3">
            {/* 执行完毕：显示精美卡片 */}
            {!isRunning && hasResults && (
              <ResultDashboard results={msg.agentResults!} />
            )}

            {/* 主动反问 */}
            {proactiveQuestion && onSend && (
              <ProactiveQuestion
                question={proactiveQuestion}
                onSend={onSend}
              />
            )}

            {/* 追问建议 */}
            {suggestionCtx && (
              <FollowUpSuggestions
                context={suggestionCtx}
                onSend={onSend!}
              />
            )}

            {msg.content && !hasResults && (
              <div
                className="inline-block px-4 py-3 rounded-2xl rounded-tl-sm text-sm prose prose-sm max-w-none dark:prose-invert overflow-x-auto break-words"
                style={{
                  backgroundColor: 'var(--bg-elevated)',
                  border: '1px solid var(--border-light)',
                  boxShadow: 'var(--shadow-sm)',
                }}
              >
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              </div>
            )}
          </div>
        )}

        <div className={`text-[11px] text-[var(--text-muted)] mt-1.5 flex items-center gap-2 ${isUser ? 'justify-end' : ''}`}>
          <span>{new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
          {!isUser && msg.startedAt && (
            <span style={{ color: isRunning ? 'var(--accent)' : 'var(--text-muted)', opacity: 0.7 }}>
              {isRunning ? `思考中 ${elapsed}s` : `思考耗时 ${elapsed}s`}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
