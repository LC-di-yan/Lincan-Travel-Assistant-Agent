import { type ReactNode } from 'react'
import type { PlanMeta } from '../../api/personal'
import { days, lifecycleLabel, pane, tripHref } from './style'

export function Section({ title, children, action, className = '' }: { title: string; children: ReactNode; action?: ReactNode; className?: string }) {
  return <section className={`${pane} ${className}`}>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-display text-xl font-semibold text-ink">{title}</h2>{action}
    </div>
    {children}
  </section>
}

export function PlanList({ rows, empty, agenda = false }: { rows: PlanMeta[]; empty: string; agenda?: boolean }) {
  if (!rows.length) return <p className="py-4 text-sm leading-6 text-ink-3">{empty}</p>
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', dateStyle: 'short' }).format(new Date())
  return <ul className="divide-y divide-rule">
    {rows.map((row) => <li key={row.plan_id}>
      <a href={tripHref(row.plan_id, agenda && row.scheduled_version != null ? `?v=${row.scheduled_version}` : '')}
        className="trip-index-row min-h-16 rounded-input px-2 py-2 hover:bg-paper-sunken focus-visible:outline-2 focus-visible:outline-accent">
        <span className="trip-date-tag">{days(agenda ? row.scheduled_start_date : row.start_date, agenda ? row.scheduled_end_date : row.end_date)}</span>
        <span className="min-w-0 max-w-full"><strong className="block break-words text-sm text-ink">{row.title}</strong>
          <span className="block text-xs text-ink-3">{!agenda && [row.origin, row.destination].filter(Boolean).join(' → ') || (agenda ? '查看已安排的版本' : '路线待定')}</span>
        </span>
        <span className="text-xs font-semibold text-route">{lifecycleLabel[row.lifecycle]} · 第 {agenda ? row.scheduled_version ?? row.current_draft_version : row.current_draft_version} 版
          {row.lifecycle === 'scheduled' && row.scheduled_end_date && (row.scheduled_end_date < today ? ' · 日期已过，待确认' : row.scheduled_start_date && row.scheduled_start_date <= today ? ' · 进行中' : '')}
          {row.scheduled_version && row.current_draft_version !== row.scheduled_version ? ' · 有新草稿' : ''}</span>
      </a>
    </li>)}
  </ul>
}
