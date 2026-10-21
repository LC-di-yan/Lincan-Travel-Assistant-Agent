import { useState, useEffect, useRef, useCallback } from 'react'
import type { FollowUpSuggestion, SuggestionContext } from '../../api/suggestionEngine'
import { generateSuggestions, recordImpression, recordClick } from '../../api/suggestionEngine'
import { fetchLLMSuggestions } from '../../api/llmSuggestions'

interface FollowUpSuggestionsProps {
  context: SuggestionContext
  onSend: (text: string) => void
}

const ANIM_STAGGER_MS = 60

function cleanSuggestion(text: string): string {
  return text.replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, '') || text
}

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allSuggestions.length])

  useEffect(() => {
    for (const s of ruleSuggestions) recordImpression(s.id)
  }, [ruleSuggestions])

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
        for (const s of llm) recordImpression(s.id)
      }
    }, 1500)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleClick = useCallback((s: FollowUpSuggestion) => {
    abortRef.current?.abort()
    recordClick(s.id)
    setExiting(true)
    setTimeout(() => onSend(s.query), 150)
  }, [onSend])

  if (allSuggestions.length === 0) return null

  return (
    <div
      className="mt-3 border-t border-rule pt-2.5"
      style={{ opacity: exiting ? 0.4 : 1, pointerEvents: exiting ? 'none' : 'auto' }}
    >
      <div className="flex flex-wrap gap-2">
        {displaySuggestions.map((s, i) => {
          const isVisible = i < visibleCount
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => handleClick(s)}
              disabled={exiting}
              className="rounded-[2px] border border-rule-strong px-2.5 py-1.5 text-[11px] text-ink-2 transition-colors hover:bg-paper-sunken hover:text-ink disabled:opacity-40"
              style={{
                opacity: isVisible ? 1 : 0,
                transform: isVisible ? 'translateY(0)' : 'translateY(3px)',
                transition: 'opacity 160ms ease, transform 160ms ease, background-color 160ms ease',
              }}
            >
              {cleanSuggestion(s.text)}
            </button>
          )
        })}
      </div>

      {allSuggestions.length > 4 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-[10px] text-ink-3 hover:text-accent"
        >
          {expanded ? '收起' : '+' + (allSuggestions.length - 4) + ' 更多'}
        </button>
      )}
    </div>
  )
}
