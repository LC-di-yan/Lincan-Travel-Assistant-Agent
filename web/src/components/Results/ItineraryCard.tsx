import { useId, useRef, useState } from 'react'
import { ChevronDown, MapPin, Utensils } from 'lucide-react'
import type { Itinerary } from '../../api/types'
import { activityTime, evidenceSources, evidenceText } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult, ResultDisclosure } from './FlightResult'
import { ExportButton } from './ExportButton'

export function ItineraryCard({ data }: { data: Record<string, unknown> }) {
  const itinerary = (data.itinerary || data) as Itinerary
  const days = Array.isArray(itinerary.daily_plans) ? itinerary.daily_plans : []
  const notes = Array.isArray(itinerary.notes) ? itinerary.notes.filter(note => evidenceText(note)) : []
  const id = useId()
  const [opened, setOpened] = useState<number[]>([0])
  const [traceDay, setTraceDay] = useState<number | null>(null)
  const traced = useRef(new Set<number>())
  if (!itinerary?.title) return null

  const allOpen = days.length > 0 && days.every((_, index) => opened.includes(index))
  const budget = evidenceText(itinerary.estimated_budget)
  const sources = evidenceSources(itinerary.sources, data.sources)

  function toggleDay(index: number) {
    const open = opened.includes(index)
    const draw = !open && !traced.current.has(index)
    if (draw) traced.current.add(index)
    setTraceDay(draw ? index : null)
    setOpened(open ? opened.filter(day => day !== index) : [...opened, index])
  }

  return <FlightResult agent="itinerary_planning" kind="逐日行程" title={itinerary.title}
    meta={<>{itinerary.duration && <span>{itinerary.duration}</span>}{itinerary.route && <span>路线示意：{itinerary.route}</span>}</>}
    action={<ExportButton itinerary={{ ...itinerary, sources }} />}>
    <EvidenceBand label="规划参考" status={budget ? `预计预算：${budget}` : '票价、房价与可订状态需核验'} sources={sources}>
      <p>{itinerary.price_notice || '行程仅供规划参考，票价、房价与可订状态请向供应方核验。'}</p>
      {notes.length > 0 && <ul className="fdr-notes" aria-label="行前备注">{notes.map((note, i) => <li key={i}>{note}</li>)}</ul>}
    </EvidenceBand>
    {days.length > 0 && <div className="fdr-section-head">
      <h4>按天查看 <small>按行程给出的顺序</small></h4>
      {days.length > 1 && <ResultDisclosure open={allOpen} onToggle={() => {
        setTraceDay(null)
        setOpened(allOpen ? [] : days.map((_, index) => index))
      }} controls={id + '-days'}>{allOpen ? '收起全部' : '展开全部'}</ResultDisclosure>}
    </div>}
    {days.length === 0 && <p className="fdr-empty">尚未提供逐日明细。</p>}
    <ol id={id + '-days'} className="fdr-days">{days.map((plan, index) => {
      const activities = Array.isArray(plan.activities) ? plan.activities : []
      const open = opened.includes(index)
      const missing = activities.filter(activity => !activityTime(activity.time)).length
      const day = typeof plan.day === 'number' ? `第 ${plan.day} 天` : evidenceText(plan.day) || `第 ${index + 1} 天`
      const detailsId = `${id}-day-${index}`
      return <li key={index} className="fdr-day" data-open={open}>
        <button type="button" className="fdr-day-switch" aria-expanded={open} aria-controls={detailsId}
          onClick={() => toggleDay(index)}>
          <span className="fdr-day-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
          <span className="fdr-day-text"><strong>{day}{plan.theme ? ` · ${plan.theme}` : ''}</strong>
            <small>{[evidenceText(plan.date) || '日期未指定', plan.city, `${activities.length} 项安排`].filter(Boolean).join(' · ')}</small>
          </span>
          {missing > 0 && <span className="fdr-mini-warn">{missing} 项时刻待核验</span>}
          <ChevronDown size={15} aria-hidden="true" />
        </button>
        <div className="fdr-day-detail" id={detailsId} hidden={!open}>
          {activities.length > 0 ? <ol className="fdr-dayrail" data-trace={traceDay === index || undefined}>
            {activities.map((act, i) => {
              const time = activityTime(act.time)
              const place = evidenceText(act.location)
              const activity = evidenceText(act.activity)
              return <li key={i} className="fdr-stop" data-unverified={!time || undefined}>
                <span className="fdr-stop-time">{time || '时刻待核验'}</span>
                <div>
                  <h5>{activity || place || '未命名活动'}</h5>
                  {place && activity && place !== activity && <p className="fdr-stop-meta"><MapPin size={13} aria-hidden="true" />{place}</p>}
                  {act.transport && <p className="fdr-stop-meta">交通：{act.transport}</p>}
                  {act.description && <p className="fdr-stop-text">{act.description}</p>}
                </div>
              </li>
            })}
          </ol> : <p className="fdr-empty">暂无活动明细。</p>}
          {(plan.meals?.lunch || plan.meals?.dinner) && <p className="fdr-meals">
            <Utensils size={14} aria-hidden="true" />
            {plan.meals.lunch && <span>午餐：{plan.meals.lunch}</span>}
            {plan.meals.dinner && <span>晚餐：{plan.meals.dinner}</span>}
          </p>}
        </div>
      </li>
    })}</ol>
  </FlightResult>
}
