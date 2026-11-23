import { useState, useEffect, useRef, useCallback } from 'react'
import type { FollowUpSuggestion, SuggestionContext } from '../../api/suggestionEngine'
import { generateSuggestions, recordImpression, recordClick } from '../../api/suggestionEngine'
import { fetchLLMSuggestions } from '../../api/llmSuggestions'

interface FollowUpSuggestionsProps {
  context: SuggestionContext
  onSend: (text: string) => void
}

function cleanSuggestion(text: string): string {
  return text.replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, '') || text
}

export function FollowUpSuggestions({ context, onSend }: FollowUpSuggestionsProps) {
  const [initialContext] = useState(context)
  const [ruleSuggestions] = useState<FollowUpSuggestion[]>(() => {
    try {
      return generateSuggestions(context)
    } catch {
      return []
    }
  })
  const [llmSuggestions, setLlmSuggestions] = useState<FollowUpSuggestion[]>([])
  const [expanded, setExpanded] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const allSuggestions = [...ruleSuggestions, ...llmSuggestions]
  const displaySuggestions = expanded ? allSuggestions : allSuggestions.slice(0, 4)

  useEffect(() => {
    for (const s of ruleSuggestions) recordImpression(s.id)
  }, [ruleSuggestions])

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    const existingTexts = new Set(ruleSuggestions.map((s) => s.text))
    const timer = setTimeout(async () => {
      const llm = await fetchLLMSuggestions(initialContext, existingTexts, controller.signal)
      if (!controller.signal.aborted) {
        setLlmSuggestions(llm)
        for (const s of llm) recordImpression(s.id)
      }
    }, 1500)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [initialContext, ruleSuggestions])

  const handleClick = useCallback((s: FollowUpSuggestion) => {
    abortRef.current?.abort()
    recordClick(s.id)
    onSend(s.query)
  }, [onSend])

  if (allSuggestions.length === 0) return null

  return (
    <div className="mt-3 border-t border-rule pt-2.5">
      <div className="flex flex-wrap gap-2">
        {displaySuggestions.map((s) => {
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => handleClick(s)}
              className="rounded-[2px] border border-rule-strong px-2.5 py-1.5 text-[11px] text-ink-2 transition-colors hover:bg-paper-sunken hover:text-ink disabled:opacity-40"
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
