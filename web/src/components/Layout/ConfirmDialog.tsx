import { useEffect, useId, useRef } from 'react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  danger = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const titleId = useId()
  const descId = useId()
  const ref = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const nodes = ref.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
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
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/35 px-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className="w-full max-w-sm rounded-[2px] border border-rule bg-paper-raised p-5 shadow-lg"
      >
        <h2 id={titleId} className="font-display text-xl text-ink">{title}</h2>
        <p id={descId} className="mt-2 text-sm leading-6 text-ink-2">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onClose}
            className="h-11 rounded-[2px] border border-rule-strong px-4 text-sm font-medium text-ink-2 hover:bg-paper-sunken"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={() => { onConfirm(); onClose() }}
            className={`h-11 rounded-[2px] px-4 text-sm font-semibold text-paper ${danger ? 'bg-err hover:opacity-90' : 'bg-accent hover:bg-accent-hover'}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
