import { useState, type KeyboardEvent } from 'react'
import { Send, Square } from 'lucide-react'

export function InputBar({ onSend, onCancel, disabled }: { onSend: (text: string) => void; onCancel: () => void; disabled: boolean }) {
  const [text, setText] = useState('')

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
  }

  const handleKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t p-4 glass" style={{ borderColor: 'var(--border)' }}>
      <div className="flex items-end gap-3 max-w-4xl mx-auto">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKey}
          placeholder="输入您的差旅需求，如：明天从北京去上海出差3天..."
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none rounded-2xl px-4 py-3 text-sm outline-none transition-all
            focus:ring-2 focus:ring-[var(--accent)] focus:shadow-[var(--shadow-glow)]
            disabled:opacity-50 placeholder:text-[var(--text-muted)]"
          style={{
            backgroundColor: 'var(--bg-primary)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
          }}
        />
        {disabled ? (
          <button
            onClick={onCancel}
            className="p-3 rounded-2xl transition-all hover:scale-105 active:scale-95"
            style={{
              background: 'var(--error)',
              color: 'white',
              boxShadow: '0 2px 8px rgba(239, 68, 68, 0.3)',
            }}
            title="停止生成"
          >
            <Square size={18} fill="currentColor" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!text.trim()}
            className="p-3 rounded-2xl transition-all disabled:opacity-40 hover:scale-105 active:scale-95"
            style={{
              background: 'linear-gradient(135deg, var(--accent), #8b5cf6)',
              color: 'white',
              boxShadow: '0 2px 8px rgba(79, 142, 247, 0.3)',
            }}
          >
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  )
}
