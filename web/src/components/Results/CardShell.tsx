import type { ReactNode } from 'react'

export function CardShell({
  children,
  className = '',
  agentName,
}: {
  children: ReactNode
  className?: string
  agentName?: string
}) {
  return (
    <div
      data-agent={agentName}
      className={`overflow-hidden rounded-[2px] border border-rule bg-paper-raised ${className}`}
    >
      {children}
    </div>
  )
}
