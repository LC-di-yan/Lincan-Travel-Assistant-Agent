import { useLayoutEffect, useRef, type ReactNode } from 'react'

/** Keep the native modal/focus lifecycle independent of the entrance animation. */
export function SurfaceDialog({ label, side = 'center', onClose, children }: {
  label: string; side?: 'left' | 'right' | 'center'; onClose: () => void; children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    const trigger = document.activeElement
    el?.showModal()
    return () => {
      el?.close()
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({ preventScroll: true })
    }
  }, [])
  return <dialog ref={ref} aria-label={label} className="deck-dialog" data-side={side}
    onCancel={e => { e.preventDefault(); onClose() }}
    onClick={e => {
      if (e.target !== e.currentTarget) return
      const r = e.currentTarget.getBoundingClientRect()
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose()
    }}>{children}</dialog>
}
