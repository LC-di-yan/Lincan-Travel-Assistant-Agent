import type { MotionChoice } from '../../hooks/useMotionPolicy'
import { ThemeToggle } from './ThemeToggle'
import { X, Volume2, Play, Square, Loader2, Check } from 'lucide-react'
import { PERSONA_ICONS, PERSONA_FALLBACK_ICON } from '../Icons'
import { useTTSPrefs, useLoadPersonas } from '../../hooks/useTTSPrefs'
import { useTTSPlayer } from '../../hooks/useTTSPlayer'

export function TTSSettings({ onClose, dark, toggle, motion, onMotion }: {
  onClose: () => void; dark: boolean; toggle: () => void; motion: MotionChoice; onMotion: (value: MotionChoice) => void
}) {
  const { prefs, personas, setPersonaId, setAutoPlay } = useTTSPrefs()
  const { status, activeMessageId, play } = useTTSPlayer()
  useLoadPersonas()

  const previewId = (pid: string) => 'preview-' + pid
  const isPreviewing = (pid: string) => activeMessageId === previewId(pid) && status !== 'idle'

  const handlePreview = (pid: string, sampleText: string) => {
    play(previewId(pid), sampleText, { personaId: pid })
  }

  return (
      <div className="p-5">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Volume2 size={16} className="text-accent" aria-hidden="true" />
            <h2 id="tts-title" className="text-sm font-semibold text-ink">显示与语音设置</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭设置" autoFocus
            className="flex h-11 w-11 items-center justify-center rounded-input text-ink-3 hover:bg-paper-sunken hover:text-ink"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="mb-4 grid gap-2 border-y border-rule py-2 text-sm">
          <div className="flex items-center justify-between"><span>外观 · {dark ? '夜间' : '日间'}</span><ThemeToggle dark={dark} toggle={toggle} /></div>
          <label className="flex items-center justify-between gap-2">动态效果
            <select className="min-h-11 rounded-input border border-rule-strong bg-paper px-2" value={motion}
              onChange={e => onMotion(e.target.value as MotionChoice)}>
              <option value="system">跟随系统</option><option value="reduced">减弱动态</option><option value="static">静态显示</option>
            </select>
          </label>
        </div>
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-semibold">语音选择</h3>
          <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto">
            {personas.length === 0 ? (
              <div className="py-4 text-center text-[11px] text-ink-3">加载角色中…</div>
            ) : personas.map((p) => {
              const selected = prefs.personaId === p.id
              const previewing = isPreviewing(p.id)
              return (
                <div
                  key={p.id}
                  className="flex items-center justify-between gap-2 rounded-input border px-3 py-2 text-[12px]"
                  style={{
                    background: selected ? 'var(--accent)' : 'var(--paper)',
                    color: selected ? 'var(--on-accent)' : 'var(--ink)',
                    borderColor: selected ? 'var(--accent)' : 'var(--rule)',
                  }}
                >
                  <button
                    type="button"
                    onClick={() => setPersonaId(p.id)}
                    className="flex min-h-11 flex-1 items-center gap-2 text-left"
                    aria-pressed={selected}
                  >
                    <PersonaGlyph id={p.id} />
                    <span>{p.label}</span>
                    {selected && <Check size={12} strokeWidth={2} aria-hidden="true" />}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handlePreview(p.id, p.sample_text)
                    }}
                    aria-label={previewing ? '停止试听' : '试听 ' + p.label}
                    className="flex h-11 w-11 items-center justify-center rounded-input hover:bg-black/10"
                    style={{ color: selected ? 'var(--on-accent)' : 'var(--accent)' }}
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

        <div className="flex items-center justify-between rounded-input border border-rule bg-paper p-3">
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
            className="grid h-11 w-11 place-items-center"
          >
            <span className="relative block h-6 w-11 rounded-full transition-colors"
              style={{ background: prefs.autoPlay ? 'var(--accent)' : 'var(--rule-strong)' }}>
              <span className="absolute left-0 top-1 h-4 w-4 rounded-full bg-paper transition-transform"
                style={{ transform: prefs.autoPlay ? 'translateX(24px)' : 'translateX(4px)' }} />
            </span>
          </button>
        </div>
      </div>
  )
}
function PersonaGlyph({ id }: { id: string }) {
  const Icon = PERSONA_ICONS[id] ?? PERSONA_FALLBACK_ICON
  return <Icon size={13} strokeWidth={1.5} className="shrink-0" aria-hidden="true" />
}
