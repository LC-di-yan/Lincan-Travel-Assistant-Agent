import { clsx } from 'clsx'

const AGENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  itinerary_planning: { icon: '/images/icons/agent-itinerary.svg', color: '#1f4e6b', label: '行程规划' },
  rag_knowledge: { icon: '/images/icons/agent-rag.svg', color: '#1f4e6b', label: '知识库' },
  event_collection: { icon: '/images/icons/agent-event.svg', color: '#2f6b4f', label: '事项收集' },
  information_query: { icon: '/images/icons/agent-info.svg', color: '#8a5a00', label: '信息查询' },
  preference: { icon: '/images/icons/agent-pref.svg', color: '#b83c22', label: '偏好管理' },
  memory_query: { icon: '/images/icons/agent-memory.svg', color: '#1f4e6b', label: '记忆查询' },
  expense_tracker: { icon: '/images/icons/agent-expense.svg', color: '#b83c22', label: '费用记录' },
  expense_tracking: { icon: '/images/icons/agent-expense.svg', color: '#b83c22', label: '费用记录' },
  currency_converter: { icon: '/images/icons/agent-currency.svg', color: '#2f6b4f', label: '汇率转换' },
  currency_conversion: { icon: '/images/icons/agent-currency.svg', color: '#2f6b4f', label: '汇率转换' },
  visa_info: { icon: '/images/icons/agent-rag.svg', color: '#1f4e6b', label: '签证信息' },
  translation: { icon: '/images/icons/agent-info.svg', color: '#1f4e6b', label: '翻译' },
  hotel_search: { icon: '/images/icons/agent-info.svg', color: '#1f4e6b', label: '酒店搜索' },
  restaurant_search: { icon: '/images/icons/agent-info.svg', color: '#8a5a00', label: '餐厅搜索' },
  scenic_search: { icon: '/images/icons/agent-info.svg', color: '#2f6b4f', label: '景点搜索' },
  train_ticket: { icon: '/images/icons/agent-info.svg', color: '#1f4e6b', label: '火车票' },
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

export function getAgentColor(agentName: string): string {
  return AGENT_CONFIG[agentName]?.color ?? '#94a3b8'
}

export function getAgentLabel(agentName: string): string {
  return AGENT_CONFIG[agentName]?.label ?? agentName
}

export { AGENT_CONFIG }
