import { lazy, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useAgentActivity } from '../../hooks/useAgentActivity'
import { messageActivity } from '../../utils/agentActivity'
import type { Message } from '../../api/types'
import { RouteBeacon } from '../Illustrations/RouteBeacon'
import { ActivityNodes } from './ActivityNodes'
import { DeferredRegion } from '../Layout/DeferredRegion'

const ActivityDetails = lazy(() => import('./ActivityDetails'))

export function ActivityAnnouncement() {
  const view = useAgentActivity()
  return <p className="sr-only" role="status" aria-atomic="true">{view.historical || view.phase === 'idle' ? '' : view.summary}</p>
}

export function RouteStrip({ message, current }: { message: Message; current: boolean }) {
  const view = useMemo(() => messageActivity(message), [message])
  const el = useRef<HTMLElement>(null)
  const [compact, setCompact] = useState(true)
  const [choice, setChoice] = useState<boolean | null>(null)
  const id = useId()
  useLayoutEffect(() => {
    const root = el.current
    if (!root || (!current && choice !== true)) return
    const sync = () => setCompact(root.clientWidth < 570)
    sync()
    const observer = new ResizeObserver(sync)
    observer.observe(root)
    return () => observer.disconnect()
  }, [current, choice])
  const open = choice ?? (current && !message.historical && !compact)
  const waiting = view.edges.find(e => view.nodes.some(n => n.id === e.to && n.status === 'pending') &&
    view.nodes.some(n => n.id === e.from && (n.status === 'running' || n.status === 'pending')))
  const name = (id: string) => view.nodes.find(n => n.id === id)?.label
  return <section ref={el} className="activity-strip" aria-label={view.live ? '处理进度' : '协作回执'} data-replay={!!message.historical}>
    <div className="activity-heading"><span className="activity-beacon"><RouteBeacon size={22} /></span>
      <div className="min-w-0 flex-1"><p className="activity-caption">{message.historical ? '历史协作记录' : view.live ? '航图台 / 协作中' : '航图台 / 本轮回执'}</p>
        <p className="activity-summary">{view.summary}</p></div>
      {!!view.nodes.length && <button type="button" className="turn-toggle min-h-11 min-w-11 text-xs text-route" aria-expanded={open}
        aria-controls={open ? id : undefined} onClick={() => setChoice(!open)}>{open ? '收起详情' : '展开详情'}</button>}
    </div>
    {message.historical && !view.nodes.length && <p className="mt-1 text-xs text-ink-3">未保存可展示的任务明细。</p>}
    {!!view.nodes.length && <p className="turn-meta mt-1 text-xs text-ink-3">列出 {view.nodes.length} 项 · 已返回 {view.returned} 项
      {view.live && waiting && <> · {name(waiting.to)}在等{name(waiting.from)}</>}</p>}
    {open && !!view.nodes.length && <div id={id}><DeferredRegion label="协作详情"
      fallback={<ActivityNodes nodes={view.nodes} />} failure={<ActivityNodes nodes={view.nodes} />}>
      <ActivityDetails view={view} compact={compact} /></DeferredRegion></div>}
  </section>
}
