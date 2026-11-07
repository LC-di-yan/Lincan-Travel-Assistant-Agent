import { clsx } from 'clsx'
import { CircleHelp } from 'lucide-react'
import { AGENT_CONFIG } from './agentConfig'

interface AgentIconProps {
  agentName: string
  size?: number
  className?: string
  showLabel?: boolean
}

export function AgentIcon({ agentName, size = 24, className, showLabel = false }: AgentIconProps) {
  const config = AGENT_CONFIG[agentName]

  if (!config) {
    return (
      <div
        className={clsx('inline-flex items-center justify-center rounded-[2px] bg-paper-sunken text-ink-3', className)}
        style={{ width: size, height: size }}
        role="img"
        aria-label={agentName}
      >
        <CircleHelp size={Math.round(size * 0.6)} strokeWidth={1.5} aria-hidden="true" />
      </div>
    )
  }

  return (
    <span className={clsx('inline-flex items-center gap-1.5', className)}>
      <img
        src={config.icon}
        alt={showLabel ? '' : config.label}
        width={size}
        height={size}
        loading="lazy"
        decoding="async"
        style={{ flexShrink: 0, filter: 'grayscale(1)', opacity: 0.72 }}
      />
      {showLabel && (
        <span className="text-xs font-medium" style={{ color: config.color }}>
          {config.label}
        </span>
      )}
    </span>
  )
}
