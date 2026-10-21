import { useEffect, useRef } from 'react'
import { X, Volume2, Play, Square, Loader2 } from 'lucide-react'
import { useTTSPrefs, useLoadPersonas } from '../../hooks/useTTSPrefs'
import { useTTSPlayer } from '../../hooks/useTTSPlayer'

export function TTSSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return <TTSSettingsBody onClose={onClose} />
}

function TTSSettingsBody({ onClose }: { onClose: () => void }) {
  const { prefs, personas, setPersonaId, setAutoPlay } = useTTSPrefs()
  const { status, activeMessageId, play } = useTTSPlayer()
  useLoadPersonas()

  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const nodes = dialogRef.current?.querySelectorAll<HTMLElement>('button, [href], input, [tabindex]:not([tabindex="-1"])')
      if (!nodes || nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const previewId = (pid: string) => 'preview-' + pid
  const isPreviewing = (pid: string) => activeMessageId === previewId(pid) && status !== 'idle'

  const handlePreview = (pid: string, sampleText: string) => {
    play(previewId(pid), sampleText, { personaId: pid })
  }

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/35"
        onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tts-title"
        className="fixed left-1/2 top-1/2 z-50 w-[92%] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-[2px] border border-rule bg-paper-raised p-5 shadow-lg"
      >
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Volume2 size={16} className="text-accent" aria-hidden="true" />
            <h2 id="tts-title" className="text-sm font-semibold text-ink">语音选择</h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="关闭语音设置"
            className="flex h-10 w-10 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="mb-4">
          <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto">
            {personas.length === 0 ? (
              <div className="py-4 text-center text-[11px] text-ink-3">加载角色中…</div>
            ) : personas.map((p) => {
              const selected = prefs.personaId === p.id
              const previewing = isPreviewing(p.id)
              return (
                <div
                  key={p.id}
                  className="flex items-center justify-between gap-2 rounded-[2px] border px-3 py-2 text-[12px]"
                  style={{
                    background: selected ? 'var(--accent)' : 'var(--paper)',
                    color: selected ? 'var(--paper)' : 'var(--ink)',
                    borderColor: selected ? 'var(--accent)' : 'var(--rule)',
                  }}
                >
                  <button
                    type="button"
                    onClick={() => setPersonaId(p.id)}
                    className="flex flex-1 items-center gap-2 text-left"
                    aria-pressed={selected}
                  >
                    <span aria-hidden="true">{p.emoji}</span>
                    <span>{p.label}</span>
                    {selected && <span aria-hidden="true">✓</span>}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handlePreview(p.id, p.sample_text)
                    }}
                    aria-label={previewing ? '停止试听' : '试听 ' + p.label}
                    className="flex h-9 w-9 items-center justify-center rounded-[2px] hover:bg-black/10"
                    style={{ color: selected ? 'var(--paper)' : 'var(--accent)' }}
                  >
                    {previewing && status === 'loading' ? (
                      <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                    ) : previewing && status === 'playing' ? (
                      <Square size={12} fill="currentColor" aria-hidden="true" />
                    ) : (
                      <Play size={12} fill="currentColor" aria-hidden="true" />
                    )}
                  </button>
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex items-center justify-between rounded-[2px] border border-rule bg-paper p-3">
          <div>
            <p className="text-[12px] font-medium text-ink">AI 语音回复</p>
            <p className="mt-0.5 text-[10px] text-ink-3">开启后，完成的回复会自动朗读。</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={prefs.autoPlay}
            aria-label="自动朗读"
            onClick={() => setAutoPlay(!prefs.autoPlay)}
            className="relative h-6 w-11 rounded-full transition-colors"
            style={{ background: prefs.autoPlay ? 'var(--accent)' : 'var(--rule-strong)' }}
          >
            <span
              className="absolute top-1 h-4 w-4 rounded-full bg-paper transition-transform"
              style={{ transform: prefs.autoPlay ? 'translateX(22px)' : 'translateX(4px)' }}
            />
          </button>
        </div>
      </div>
    </>
  )
}
