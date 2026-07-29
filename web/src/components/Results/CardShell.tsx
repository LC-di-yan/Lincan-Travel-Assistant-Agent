import type { ReactNode } from 'react'
import { getAgentColor } from '../Icons'

export function CardShell({
  children,
  className = '',
  agentName,
}: {
  children: ReactNode
  className?: string
  agentName?: string
}) {
  const accentColor = agentName ? getAgentColor(agentName) : undefined

  return (
    <div
      className={`rounded-2xl overflow-hidden animate-fade-in-up ${className}`}
      style={{
        border: '1px solid var(--border)',
        borderLeft: accentColor ? `3px solid ${accentColor}` : undefined,
        backgroundColor: 'var(--bg-elevated)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      {children}
    </div>
  )
}
