import { useState } from 'react'

interface ProactiveQuestionProps {
  question: string
  onSend: (text: string) => void
}

function transformQuestion(question: string): string {
  if (typeof question !== 'string') return ''
  return question.replace(/^需要我帮你/, '请帮我').replace(/吗[？?]?$/, '')
}

export function ProactiveQuestion({ question, onSend }: ProactiveQuestionProps) {
  const [clicked, setClicked] = useState(false)

  if (!question) return null

  const handleClick = () => {
    if (clicked) return
    setClicked(true)
    const text = transformQuestion(question)
    if (text) onSend(text)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={clicked}
      className="flex w-full items-start gap-3 rounded-[2px] border border-rule-strong bg-paper-raised px-3 py-2.5 text-left transition-colors hover:bg-paper-sunken disabled:opacity-50"
    >
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-[2px] border border-accent font-mono text-[11px] font-bold text-accent"
      >
        ?
      </span>
      <span className="min-w-0 flex-1 text-[13px] leading-6 text-ink">{question}</span>
      <span className="ml-2 shrink-0 text-[11px] font-semibold text-accent">帮我问 →</span>
    </button>
  )
}
