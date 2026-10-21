import { useState, useEffect, useRef, type KeyboardEvent } from 'react'
import { Send, Square, Mic } from 'lucide-react'
import { useSpeechRecognition } from '../../hooks/useSpeechRecognition'

export function InputBar({ onSend, onCancel, disabled }: { onSend: (text: string) => void; onCancel: () => void; disabled: boolean }) {
  const [text, setText] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)
  const {
    isListening,
    isSupported,
    interimText,
    finalText,
    startListening,
    stopListening,
    reset,
  } = useSpeechRecognition({ lang: 'zh-CN', continuous: false, interimResults: true })

  useEffect(() => {
    if (!isListening && finalText) {
      setText((prev) => (prev ? prev + finalText : finalText))
      reset()
    }
  }, [isListening, finalText, reset])

  useEffect(() => {
    if (disabled && isListening) stopListening()
  }, [disabled, isListening, stopListening])

  const displayText = isListening && interimText ? text + interimText : text

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, [displayText])

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    if (isListening) stopListening()
  }

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return
    if (e.nativeEvent.isComposing) return
    e.preventDefault()
    handleSend()
  }

  return (
    <div className="flex-shrink-0 border-t border-rule bg-paper px-3 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 md:px-4">
      <div className="mx-auto w-full max-w-[760px]">
        <div className="flex items-end gap-1.5 rounded-[2px] border border-rule-strong bg-paper-raised px-2 py-1.5 transition-colors focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/10">
          <textarea
            ref={taRef}
            value={displayText}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKey}
            placeholder={isListening ? '正在聆听…' : '说需求，或粘贴航班号…'}
            rows={1}
            aria-label="输入消息"
            className="max-h-[120px] min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 text-ink outline-none placeholder:text-ink-3 disabled:opacity-50"
          />

          {isSupported && (
            <button
              type="button"
              onClick={() => (isListening ? stopListening() : startListening())}
              disabled={disabled && !isListening}
              aria-label={isListening ? '停止语音输入' : '语音输入'}
              title={isListening ? '停止语音输入' : '语音输入'}
              className={`flex h-11 w-11 items-center justify-center rounded-[2px] transition-colors disabled:opacity-40 ${
                isListening
                  ? 'bg-err text-white'
                  : 'text-ink-3 hover:bg-paper-sunken hover:text-ink'
              }`}
            >
              <Mic size={18} aria-hidden="true" fill={isListening ? 'currentColor' : 'none'} />
            </button>
          )}

          {disabled ? (
            <button
              type="button"
              onClick={onCancel}
              aria-label="停止生成"
              title="停止生成"
              className="flex h-11 w-11 items-center justify-center rounded-[2px] bg-err text-white hover:opacity-90"
            >
              <Square size={16} fill="currentColor" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSend}
              disabled={!text.trim()}
              aria-label="发送消息"
              title="发送"
              className="flex h-11 w-11 items-center justify-center rounded-[2px] bg-accent text-paper transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-rule disabled:text-ink-3"
            >
              <Send size={17} aria-hidden="true" />
            </button>
          )}
        </div>

        <div className="mt-1.5 flex items-center justify-between px-1 font-mono text-[10px] tracking-[0.04em] text-ink-3">
          <span className="hidden sm:inline">Enter 发送 · Shift+Enter 换行</span>
          <span className="sm:hidden">Enter 发送</span>
          <span>AI 可能会出错，请核对关键信息</span>
        </div>
      </div>
    </div>
  )
}
