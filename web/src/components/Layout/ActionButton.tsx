import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { MagneticButton } from '../effects/MagneticButton'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  intent?: 'primary' | 'secondary' | 'stop'
  icon?: ReactNode
  /** 传入监听指针的容器时启用磁吸；为空时保持普通按钮。 */
  magnetic?: HTMLElement | null
  /** 磁吸最大偏移（px）；不传时用组件默认值。 */
  magneticPull?: number
}

export function ActionButton({ intent = 'secondary', icon, children, className = '', type = 'button', magnetic = null, magneticPull, ...props }: Props) {
  const inner = <span className="action-inner">{children}{icon && <span className="action-glyph" aria-hidden="true">{icon}</span>}</span>
  if (magnetic) {
    return <MagneticButton bare watch={magnetic} pull={magneticPull} type={type} className={`deck-action ${className}`} data-intent={intent} {...props}>
      {inner}
    </MagneticButton>
  }
  return <button type={type} className={`deck-action ${className}`} data-intent={intent} {...props}>
    {inner}
  </button>
}
