import { Target, Zap } from 'lucide-react'
import { useChatStore } from '../../store/chatStore'

const intentLabels: Record<string, string> = {
  itinerary_planning: '行程规划',
  preference: '偏好管理',
  information_query: '信息查询',
  rag_knowledge: '知识问答',
  memory_query: '记忆查询',
  event_collection: '事项收集',
}

export function IntentPanel() {
  const intention = useChatStore((s) => s.currentIntention)
  const agents = useChatStore((s) => s.currentAgents)
  const isProcessing = useChatStore((s) => s.isProcessing)

  if (!intention && !isProcessing) {
    return (
      <div className="p-6 text-center text-xs text-[var(--text-muted)]">
        <img src="/images/illustrations/no-intent.svg" alt="等待分析" className="w-28 h-auto mx-auto mb-3 opacity-80" />
        <p className="font-medium">发送消息后</p>
        <p>意图分析将在此显示</p>
      </div>
    )
  }

  return (
    <div className="p-3 space-y-4">
      {intention?.intents && intention.intents.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--text-muted)] mb-2.5 flex items-center gap-1">
            <Target size={10} /> 识别意图
          </h4>
          {intention.intents.map((intent, i) => (
            <div key={i} className="mb-2.5">
              <div className="flex items-center justify-between text-xs mb-1.5">
                <span className="font-medium">{intentLabels[intent.type] || intent.type}</span>
                <span className="text-[var(--accent)] font-semibold">{(intent.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                <div className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${intent.confidence * 100}%`,
                    background: intent.confidence > 0.7
                      ? 'linear-gradient(90deg, var(--success), #34d399)'
                      : 'linear-gradient(90deg, var(--warning), #fbbf24)',
                  }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {intention?.key_entities && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--text-muted)] mb-2.5">关键信息</h4>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(intention.key_entities).map(([key, value]) => {
              if (!value) return null
              const labels: Record<string, string> = {
                origin: '📍出发地', destination: '📍目的地', date: '📅日期', duration: '⏱️时长', other: '📌其他',
              }
              return (
                <span key={key} className="text-xs px-2.5 py-1 rounded-full font-medium"
                  style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}>
                  {labels[key] || key}: {String(value)}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {intention?.agent_schedule && intention.agent_schedule.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--text-muted)] mb-2.5 flex items-center gap-1">
            <Zap size={10} /> 调度计划
          </h4>
          <div className="space-y-1.5">
            {intention.agent_schedule.map((a, i) => {
              const result = agents.find((r) => r.agent_name === a.agent_name)
              const status = result ? result.status : isProcessing ? 'running' : 'pending'
              return (
                <div key={i} className="flex items-center gap-2 text-xs p-2 rounded-lg transition-all"
                  style={{ backgroundColor: 'var(--bg-secondary)' }}>
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    status === 'success' ? 'bg-[var(--success)]' :
                    status === 'error' ? 'bg-[var(--error)]' :
                    status === 'running' ? 'bg-[var(--warning)] animate-pulse' :
                    'bg-[var(--text-muted)]'
                  }`} />
                  <span className="flex-1 truncate">{intentLabels[a.agent_name] || a.agent_name}</span>
                  <span className="text-[var(--text-muted)] font-mono">P{a.priority}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {intention?.reasoning && (
        <div className="text-xs p-3 rounded-xl flex items-start gap-2"
          style={{ backgroundColor: 'var(--bg-secondary)' }}>
          <span className="text-[var(--accent)] flex-shrink-0 mt-0.5">💡</span>
          <p className="text-[var(--text-secondary)] leading-relaxed">
            {intention.reasoning}
          </p>
        </div>
      )}
    </div>
  )
}
