import type { PlanEvent, PlanMeta, PlanVersion } from '../../api/personal'
import { dayTime, days, tripHref } from './style'
import './trip-rhythm.css'

const dateKey = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', dateStyle: 'short' })
const noDate = '日期待定'

function activityDay(event: PlanEvent) {
  const start = event.start_at ? Date.parse(event.start_at) : NaN
  return Number.isFinite(start) ? dateKey.format(start) : event.local_date || noDate
}

const eventTime = (e: PlanEvent) => e.start_at && e.end_at
  ? `${e.precision === 'window' ? '约 ' : ''}${dayTime(e.start_at)} → ${dayTime(e.end_at)}`
  : e.local_date ? days(e.local_date, e.end_date) + '（时刻待定）' : '时间待定'

export function EventRows({ values, compact = false }: { values: PlanEvent[]; compact?: boolean }) {
  const groups = new Map<string, PlanEvent[]>()
  for (const row of [...values].sort((a, b) => {
    const day = (activityDay(a) === noDate ? '9999' : activityDay(a)).localeCompare(activityDay(b) === noDate ? '9999' : activityDay(b))
    return day || (Date.parse(a.start_at || '') || Infinity) - (Date.parse(b.start_at || '') || Infinity)
  })) {
    const key = activityDay(row)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(row)
  }
  if (!groups.size) return <p className="py-2 text-sm text-ink-3">还没有具体活动。</p>
  return <div className="trip-days" data-compact={compact || undefined}>
    {[...groups].map(([day, events]) => <div key={day}>
      <h4>{day}</h4>
      <ol>{events.map((row, index) => <li key={row.event_id || index} data-uncertain={row.precision !== 'exact' || undefined}>
        <span className="trip-event-time">{eventTime(row)}</span>
        <div><strong>{row.title}</strong>
          {(row.place || row.city || row.arrival_place || row.arrival_city) && <p>{[row.place || row.city, row.arrival_place || row.arrival_city].filter(Boolean).join(' → ')}</p>}
          {!compact && row.notes && <p>{row.notes}</p>}
        </div>
      </li>)}</ol>
    </div>)}
  </div>
}

export function VersionBoard({ plan, shown }: { plan: PlanMeta; shown: PlanVersion }) {
  const scheduled = plan.lifecycle === 'scheduled' ? plan.scheduled_version : null
  const versionLink = (version: number) => tripHref(plan.plan_id, `?v=${version}`)
  return <div className="trip-version-board" aria-label="查看、草稿与安排版本" role="group">
    <div data-viewing><span>正在查看</span><b>第 {shown.version} 版</b>
      <small>{shown.version === plan.current_draft_version ? '当前草稿版本' : shown.version === scheduled ? '日历正在使用这一版' : '历史快照，不改变草稿或日历'}</small></div>
    <div><span>当前草稿</span><b>第 {plan.current_draft_version} 版</b>
      {plan.current_draft_version !== shown.version
        ? <a href={tripHref(plan.plan_id)}>查看当前草稿</a> : <small>保存或修改草稿不会更新日历</small>}</div>
    <div data-arranged={scheduled != null || undefined}><span>实际安排</span><b>{scheduled != null ? `第 ${scheduled} 版` : '未占用日历'}</b>
      {scheduled != null ? <>{scheduled !== shown.version && <a href={versionLink(scheduled)}>查看已安排版本</a>}
        <small>当前安排使用第 {scheduled} 版</small></> : <small>预检不会加入安排</small>}</div>
  </div>
}
