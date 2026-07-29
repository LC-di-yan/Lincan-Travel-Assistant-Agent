import { clsx } from 'clsx'

const AGENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  itinerary_planning: { icon: '/images/icons/agent-itinerary.svg', color: '#4f8ef7', label: '行程规划' },
  rag_knowledge: { icon: '/images/icons/agent-rag.svg', color: '#8b5cf6', label: '知识库' },
  event_collection: { icon: '/images/icons/agent-event.svg', color: '#10b981', label: '事项收集' },
  information_query: { icon: '/images/icons/agent-info.svg', color: '#f59e0b', label: '信息查询' },
  preference: { icon: '/images/icons/agent-pref.svg', color: '#ec4899', label: '偏好管理' },
  memory_query: { icon: '/images/icons/agent-memory.svg', color: '#06b6d4', label: '记忆查询' },
  expense_tracker: { icon: '/images/icons/agent-expense.svg', color: '#f97316', label: '费用记录' },
  currency_converter: { icon: '/images/icons/agent-currency.svg', color: '#14b8a6', label: '汇率转换' },
  visa_info: { icon: '/images/icons/agent-rag.svg', color: '#6366f1', label: '签证信息' },
  translation: { icon: '/images/icons/agent-info.svg', color: '#0ea5e9', label: '翻译' },
}

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
        className={clsx('inline-flex items-center justify-center rounded-lg', className)}
        style={{ width: size, height: size, backgroundColor: '#94a3b820' }}
      >
        <span style={{ fontSize: size * 0.5, color: '#94a3b8' }}>?</span>
      </div>
    )
  }

  return (
    <span className={clsx('inline-flex items-center gap-1.5', className)}>
      <img
        src={config.icon}
        alt={config.label}
        width={size}
        height={size}
        style={{ flexShrink: 0 }}
      />
      {showLabel && (
        <span className="text-xs font-medium" style={{ color: config.color }}>
          {config.label}
        </span>
      )}
    </span>
  )
}

export function getAgentColor(agentName: string): string {
  return AGENT_CONFIG[agentName]?.color ?? '#94a3b8'
}

export function getAgentLabel(agentName: string): string {
  return AGENT_CONFIG[agentName]?.label ?? agentName
}

export { AGENT_CONFIG }
