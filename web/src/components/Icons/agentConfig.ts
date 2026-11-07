/** Agent 元数据（纯数据模块，与组件分文件以满足 react-refresh） */
export const AGENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  itinerary_planning: { icon: '/images/icons/agent-itinerary.svg', color: 'var(--route)', label: '行程规划' },
  rag_knowledge: { icon: '/images/icons/agent-rag.svg', color: 'var(--route)', label: '知识库' },
  event_collection: { icon: '/images/icons/agent-event.svg', color: 'var(--ok)', label: '事项收集' },
  information_query: { icon: '/images/icons/agent-info.svg', color: 'var(--warn)', label: '信息查询' },
  preference: { icon: '/images/icons/agent-pref.svg', color: 'var(--accent)', label: '偏好管理' },
  memory_query: { icon: '/images/icons/agent-memory.svg', color: 'var(--route)', label: '记忆查询' },
  expense_tracker: { icon: '/images/icons/agent-expense.svg', color: 'var(--accent)', label: '费用记录' },
  expense_tracking: { icon: '/images/icons/agent-expense.svg', color: 'var(--accent)', label: '费用记录' },
  currency_converter: { icon: '/images/icons/agent-currency.svg', color: 'var(--ok)', label: '汇率转换' },
  currency_conversion: { icon: '/images/icons/agent-currency.svg', color: 'var(--ok)', label: '汇率转换' },
  visa_info: { icon: '/images/icons/agent-rag.svg', color: 'var(--route)', label: '签证信息' },
  translation: { icon: '/images/icons/agent-info.svg', color: 'var(--route)', label: '翻译' },
  hotel_search: { icon: '/images/icons/agent-info.svg', color: 'var(--route)', label: '酒店搜索' },
  restaurant_search: { icon: '/images/icons/agent-info.svg', color: 'var(--warn)', label: '餐厅搜索' },
  scenic_search: { icon: '/images/icons/agent-info.svg', color: 'var(--ok)', label: '景点搜索' },
  train_ticket: { icon: '/images/icons/agent-info.svg', color: 'var(--route)', label: '火车票' },
}

/** 未识别 agent 的中性色：走主题 token，避免硬编码冷灰与暖纸底冲突 */
export const AGENT_FALLBACK_COLOR = 'var(--ink-3)'

export function getAgentColor(agentName: string): string {
  return AGENT_CONFIG[agentName]?.color ?? AGENT_FALLBACK_COLOR
}

export function getAgentLabel(agentName: string): string {
  return AGENT_CONFIG[agentName]?.label ?? agentName
}
