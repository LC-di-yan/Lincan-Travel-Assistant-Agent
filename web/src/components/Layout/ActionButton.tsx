import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  intent?: 'primary' | 'secondary' | 'stop'
  icon?: ReactNode
}

export function ActionButton({ intent = 'secondary', icon, children, className = '', type = 'button', ...props }: Props) {
  return <button type={type} className={`deck-action ${className}`} data-intent={intent} {...props}>
    <span className="action-inner">{children}{icon && <span className="action-glyph" aria-hidden="true">{icon}</span>}</span>
  </button>
}
