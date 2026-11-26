import { useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react'

/** Keep the native modal/focus lifecycle independent of the entrance animation. */
export function SurfaceDialog({ label, side = 'center', onClose, children, returnFocus }: {
  label: string; side?: 'left' | 'right' | 'center'; onClose: () => void; children: ReactNode
  returnFocus?: RefObject<HTMLButtonElement | null>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    const trigger = returnFocus?.current ?? document.activeElement
    el?.showModal()
    return () => {
      el?.close()
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({ preventScroll: true })
    }
  }, [returnFocus])
  return <dialog ref={ref} aria-label={label} className="deck-dialog" data-side={side}
    onCancel={e => { e.preventDefault(); onClose() }}
    onClick={e => {
      if (e.target !== e.currentTarget) return
      const r = e.currentTarget.getBoundingClientRect()
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose()
    }}>{children}</dialog>
}
