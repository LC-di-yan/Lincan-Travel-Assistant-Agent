import { useChatStore } from '../../store/chatStore'
import { getAgentLabel } from '../Icons/AgentIcon'

const intentLabels: Record<string, string> = {
  itinerary_planning: '行程规划',
  preference: '偏好管理',
  information_query: '信息查询',
  rag_knowledge: '知识问答',
  memory_query: '记忆查询',
  event_collection: '事项收集',
  hotel_search: '酒店搜索',
  restaurant_search: '餐厅搜索',
  scenic_search: '景点搜索',
  currency_conversion: '汇率转换',
  translation: '翻译',
  expense_tracking: '费用记录',
  visa_info: '签证信息',
  train_ticket: '火车票',
}

const ENTITY_LABELS: Record<string, string> = {
  origin: '出发地',
  destination: '目的地',
  date: '日期',
  duration: '时长',
  other: '其他',
}

export function IntentPanel() {
  const intention = useChatStore((s) => s.currentIntention)
  const agents = useChatStore((s) => s.currentAgents)
  const isProcessing = useChatStore((s) => s.isProcessing)

  if (!intention && !isProcessing) {
    return (
      <div className="p-4">
        <div className="font-mono text-[9px] tracking-[0.16em] text-accent">INTENT / 意图</div>
        <p className="mt-2 text-[12px] leading-6 text-ink-2">
          发送消息后，这里会显示识别出的意图、关键信息和调度计划。
        </p>
        <div className="mt-4 border-t border-rule pt-1">
          {['识别意图', '提取要素', '调度子任务'].map((label, i) => (
            <div key={label} className="flex items-center gap-2 border-b border-rule py-2 text-[11px] text-ink-3 last:border-0">
              <span className="font-mono text-accent">0{i + 1}</span>
              {label}
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div>
      {intention?.intents && intention.intents.length > 0 && (
        <section className="border-b border-rule px-4 py-3">
          <div className="mb-2 font-mono text-[9px] tracking-[0.14em] text-ink-3">INTENT</div>
          {intention.intents.map((intent, i) => {
            const pct = Math.round(intent.confidence * 100)
            return (
              <div key={i} className="border-b border-rule py-2 last:border-0">
                <div className="flex items-baseline justify-between text-[11px]">
                  <span className="text-ink">{intentLabels[intent.type] || intent.type}</span>
                  <span className="font-mono tabular text-accent">{pct}%</span>
                </div>
                <div className="mt-1 h-1 bg-paper-sunken">
                  <div
                    className={pct < 70 ? 'h-full bg-warn' : 'h-full bg-accent'}
                    style={{ width: pct + '%' }}
                  />
                </div>
              </div>
            )
          })}
        </section>
      )}

      {intention?.key_entities && (
        <section className="border-b border-rule px-4 py-3">
          <div className="mb-2 font-mono text-[9px] tracking-[0.14em] text-ink-3">ENTITIES</div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(intention.key_entities).map(([key, value]) => {
              if (!value) return null
              return (
                <span key={key} className="rounded-[2px] border border-rule px-2 py-1 text-[10px]">
                  <span className="text-ink-3">{ENTITY_LABELS[key] || key}</span>
                  <span className="ml-1 text-ink">{String(value)}</span>
                </span>
              )
            })}
          </div>
        </section>
      )}

      {intention?.agent_schedule && intention.agent_schedule.length > 0 && (
        <section className="border-b border-rule px-4 py-3">
          <div className="mb-1 font-mono text-[9px] tracking-[0.14em] text-ink-3">SCHEDULE</div>
          {intention.agent_schedule.map((a, i) => {
            const result = agents.find((r) => r.agent_name === a.agent_name)
            const status = result ? result.status : isProcessing ? 'running' : 'pending'
            return (
              <div key={i} className="flex items-center gap-2 border-b border-rule py-2 text-[11px] last:border-0">
                <span
                  aria-hidden="true"
                  className={
                    'h-1.5 w-1.5 shrink-0 rounded-full ' +
                    (status === 'success'
                      ? 'bg-ok'
                      : status === 'error'
                        ? 'bg-err'
                        : status === 'running'
                          ? 'bg-accent'
                          : 'border border-rule-strong bg-transparent')
                  }
                />
                <span className="flex-1 truncate text-ink-2">{intentLabels[a.agent_name] || getAgentLabel(a.agent_name)}</span>
                <span className="font-mono text-[9px] text-ink-3">P{a.priority}</span>
              </div>
            )
          })}
        </section>
      )}

      {intention?.reasoning && (
        <section className="px-4 py-3">
          <div className="mb-1 font-mono text-[9px] tracking-[0.14em] text-ink-3">REASONING</div>
          <p className="border-l-2 border-accent pl-2 text-[11px] leading-5 text-ink-2">{intention.reasoning}</p>
        </section>
      )}
    </div>
  )
}
