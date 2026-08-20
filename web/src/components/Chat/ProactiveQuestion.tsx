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
    try {
      const text = transformQuestion(question)
      if (text) onSend(text)
    } catch (e) {
      console.error('ProactiveQuestion send error:', e)
    }
  }

  return (
    <div
      onClick={handleClick}
      className="rounded-2xl px-4 py-3 cursor-pointer transition-all duration-200 hover:shadow-md active:scale-[0.98] select-none flex items-center gap-2"
      style={{
        backgroundColor: '#FFFFFF',
        border: '1.5px dashed #F9A825',
        opacity: clicked ? 0.5 : 1,
      }}
    >
      <img
        src="/images/反问框图片.jpeg"
        alt=""
        className="w-[72px] h-[72px] rounded-full object-cover flex-shrink-0"
      />
      <span className="text-[18px]" style={{ color: '#795548' }}>
        {question}
      </span>
    </div>
  )
}
