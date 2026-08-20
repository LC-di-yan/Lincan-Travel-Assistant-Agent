import { useState, useEffect, useRef, useCallback } from 'react'
import type { FollowUpSuggestion, SuggestionContext } from '../../api/suggestionEngine'
import { generateSuggestions, recordImpression, recordClick } from '../../api/suggestionEngine'
import { fetchLLMSuggestions } from '../../api/llmSuggestions'

interface FollowUpSuggestionsProps {
  context: SuggestionContext
  onSend: (text: string) => void
}

const ANIM_STAGGER_MS = 60

export function FollowUpSuggestions({ context, onSend }: FollowUpSuggestionsProps) {
  const [ruleSuggestions] = useState<FollowUpSuggestion[]>(() => {
    try {
      return generateSuggestions(context)
    } catch {
      return []
    }
  })
  const [llmSuggestions, setLlmSuggestions] = useState<FollowUpSuggestion[]>([])
  const [visibleCount, setVisibleCount] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [exiting, setExiting] = useState(false)
  const llmFetched = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  const allSuggestions = [...ruleSuggestions, ...llmSuggestions]
  const displaySuggestions = expanded ? allSuggestions : allSuggestions.slice(0, 4)

  // 逐条入场动画
  useEffect(() => {
    setVisibleCount(0)
    if (allSuggestions.length === 0) return
    const timer = setInterval(() => {
      setVisibleCount((prev) => {
        if (prev >= allSuggestions.length) {
          clearInterval(timer)
          return prev
        }
        return prev + 1
      })
    }, ANIM_STAGGER_MS)
    return () => clearInterval(timer)
  }, [ruleSuggestions.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // 记录规则建议的展示
  useEffect(() => {
    for (const s of ruleSuggestions) {
      recordImpression(s.id)
    }
  }, [ruleSuggestions])

  // LLM 渐进生成：延迟 1.5s 后发起，用户操作则取消
  useEffect(() => {
    if (llmFetched.current) return
    llmFetched.current = true

    const controller = new AbortController()
    abortRef.current = controller

    const existingTexts = new Set(ruleSuggestions.map((s) => s.text))
    const timer = setTimeout(async () => {
      const llm = await fetchLLMSuggestions(context, existingTexts, controller.signal)
      if (!controller.signal.aborted) {
        setLlmSuggestions(llm)
        for (const s of llm) {
          recordImpression(s.id)
        }
      }
    }, 1500)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 点击追问
  const handleClick = useCallback((s: FollowUpSuggestion) => {
    // 取消 LLM 请求
    abortRef.current?.abort()
    recordClick(s.id)
    setExiting(true)
    setTimeout(() => onSend(s.query), 150)
  }, [onSend])

  if (allSuggestions.length === 0) return null

  return (
    <div
      className="mt-3 pt-3"
      style={{
        borderTop: '1px dashed var(--border-light)',
        opacity: exiting ? 0.4 : 1,
        transition: 'opacity 0.3s ease',
        pointerEvents: exiting ? 'none' : 'auto',
      }}
    >
      <div className="flex flex-wrap gap-2">
        {displaySuggestions.map((s, i) => {
          const isVisible = i < visibleCount
          const isLlm = s.source === 'llm'
          const chipStyle = getChipStyle(s.type)

          return (
            <button
              key={s.id}
              onClick={() => handleClick(s)}
              className="text-left transition-all duration-200 active:scale-95"
              style={{
                fontSize: chipStyle.fontSize,
                padding: chipStyle.padding,
                border: chipStyle.border,
                borderRadius: '9999px',
                backgroundColor: chipStyle.bg,
                color: 'var(--text-primary)',
                cursor: 'pointer',
                opacity: isVisible ? 1 : 0,
                transform: isVisible
                  ? 'scale(1) translateY(0)'
                  : 'scale(0.92) translateY(6px)',
                transition: `opacity 0.3s ease, transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.2s ease, background-color 0.2s ease`,
                animation: isLlm && isVisible ? 'slide-in-right 0.35s cubic-bezier(0.16, 1, 0.3, 1) both' : undefined,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent)'
                e.currentTarget.style.backgroundColor = 'var(--accent-light)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = chipStyle.borderColor
                e.currentTarget.style.backgroundColor = chipStyle.bg
              }}
            >
              {s.text}
            </button>
          )
        })}
      </div>

      {/* 超过 4 条折叠 */}
      {allSuggestions.length > 4 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[11px] mt-2 px-2 py-0.5 rounded-full transition-colors hover:bg-[var(--bg-secondary)]"
          style={{ color: 'var(--accent)' }}
        >
          {expanded ? '收起' : `+${allSuggestions.length - 4} 更多`}
        </button>
      )}

      <style>{`
        @keyframes slide-in-right {
          from { opacity: 0; transform: translateX(20px) scale(0.94); }
          to { opacity: 1; transform: translateX(0) scale(1); }
        }
      `}</style>
    </div>
  )
}

interface ChipStyle {
  fontSize: string
  padding: string
  border: string
  borderColor: string
  bg: string
}

function getChipStyle(type: FollowUpSuggestion['type']): ChipStyle {
  switch (type) {
    case 'deepen':
      return {
        fontSize: '13px',
        padding: '6px 14px',
        border: '1px solid var(--accent)',
        borderColor: 'var(--accent)',
        bg: 'var(--accent-light)',
      }
    case 'explore':
      return {
        fontSize: '12px',
        padding: '5px 12px',
        border: '1px dashed var(--border)',
        borderColor: 'var(--border)',
        bg: 'transparent',
      }
    case 'action':
      return {
        fontSize: '11px',
        padding: '4px 10px',
        border: '1px dotted var(--border-light)',
        borderColor: 'var(--border-light)',
        bg: 'transparent',
      }
    case 'fallback':
      return {
        fontSize: '11px',
        padding: '4px 10px',
        border: '1px dotted var(--border-light)',
        borderColor: 'var(--border-light)',
        bg: 'transparent',
      }
  }
}
