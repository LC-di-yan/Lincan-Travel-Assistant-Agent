import { Dependencies } from '../Chat/ActivityDetails'
import { useChatStore } from '../../store/chatStore'
import { useAgentActivity } from '../../hooks/useAgentActivity'
import { ActivityNodes } from '../Chat/ActivityNodes'
import { RouteBeacon } from '../Illustrations/RouteBeacon'

const fields = { origin: '出发地', destination: '目的地', date: '日期', duration: '时长' } as const

export function IntentPanel() {
  const view = useAgentActivity()
  const { nodes, summary } = view
  const entities = useChatStore(s => s.messages.at(-1)?.intention?.key_entities)
  return <div className="activity-detail">
    <div className="flex items-center gap-2 text-route"><RouteBeacon size={21} /><h3 className="text-sm font-semibold">{view.historical ? '历史协作记录' : '协作状态'}</h3></div>
    <p className="activity-summary">{summary}</p>
    <ActivityNodes nodes={nodes} /><Dependencies view={view} />
    {!nodes.length && view.phase === 'idle' && <p className="mt-2 text-sm leading-6 text-ink-3">有任务开始或返回结果时，会在这里列出。</p>}
    {entities && <dl className="mt-5 divide-y divide-rule">{(Object.keys(fields) as (keyof typeof fields)[]).map(key =>
      typeof entities[key] === 'string' && entities[key]?.trim() ? <div key={key} className="flex items-baseline justify-between gap-3 py-2 text-sm">
        <dt className="shrink-0 text-ink-3">{fields[key]}</dt><dd className="break-words text-right">{entities[key]}</dd>
      </div> : null)}</dl>}
  </div>
}
