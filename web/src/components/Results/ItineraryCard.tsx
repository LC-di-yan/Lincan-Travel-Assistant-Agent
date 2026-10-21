import { useState } from 'react'
import { Clock, Utensils, ChevronDown, ChevronRight, StickyNote } from 'lucide-react'
import type { Itinerary, DailyPlan } from '../../api/types'
import { CardShell } from './CardShell'
import { ExportButton } from './ExportButton'

function DailyPlanItem({ plan }: { plan: DailyPlan }) {
  const [open, setOpen] = useState(true)
  const dayLabel = typeof plan.day === 'number' ? `第 ${plan.day} 天` : plan.day
  const meta = [plan.date, plan.city, plan.theme].filter(Boolean).join(' · ')

  return (
    <div className="relative pb-3 pl-5">
      <div className="absolute bottom-0 left-[5px] top-2 w-px bg-rule" aria-hidden="true" />
      <div className="absolute left-0 top-2 h-2.5 w-2.5 rounded-full border border-accent bg-paper-raised" aria-hidden="true" />

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 text-[13px] font-semibold text-ink hover:text-accent"
      >
        {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
        {dayLabel}
        {meta && <span className="ml-1 text-[10px] font-normal text-ink-3">{meta}</span>}
      </button>

      {open && (
        <div className="mt-1">
          {(plan.activities || []).map((act, i) => (
            <div key={i} className="flex gap-3 border-b border-rule py-2 text-[13px] last:border-0">
              <span className="w-[72px] shrink-0 font-mono text-[10px] tabular text-ink-3">
                {act.time || '—'}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="font-medium text-ink">{act.activity || '未命名活动'}</span>
                  {act.transport && <span className="text-[11px] text-route">{act.transport}</span>}
                </div>
                {act.description && (
                  <p className="mt-0.5 text-[12px] leading-5 text-ink-2">{act.description}</p>
                )}
              </div>
            </div>
          ))}

          {(plan.meals?.lunch || plan.meals?.dinner) && (
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 pl-1 text-[11px] text-ink-2">
              {plan.meals?.lunch && (
                <span className="inline-flex items-center gap-1">
                  <Utensils size={10} aria-hidden="true" /> 午：{plan.meals.lunch}
                </span>
              )}
              {plan.meals?.dinner && (
                <span className="inline-flex items-center gap-1">
                  <Utensils size={10} aria-hidden="true" /> 晚：{plan.meals.dinner}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ItineraryCard({ data }: { data: Record<string, unknown> }) {
  const itinerary = (data.itinerary || data) as Itinerary
  if (!itinerary?.title) return null

  return (
    <CardShell agentName="itinerary_planning">
      <div className="flex items-start justify-between gap-3 border-b border-rule px-4 py-3">
        <div className="min-w-0">
          <div className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / ITINERARY</div>
          <h3 className="mt-1 font-display text-lg leading-snug text-ink">{itinerary.title}</h3>
          {itinerary.duration && (
            <p className="mt-0.5 flex items-center gap-1 text-[11px] text-ink-3">
              <Clock size={10} aria-hidden="true" /> {itinerary.duration}
            </p>
          )}
        </div>
        <ExportButton itinerary={itinerary} />
      </div>

      <div className="p-4">
        {itinerary.daily_plans?.map((plan, i) => (
          <DailyPlanItem key={i} plan={plan} />
        ))}

        {itinerary.notes && itinerary.notes.length > 0 && (
          <div className="mt-3 border border-warn/30 bg-warning-light p-3 text-[12px]">
            <div className="mb-1 flex items-center gap-1 font-medium text-ink">
              <StickyNote size={12} aria-hidden="true" /> 注意事项
            </div>
            <ul className="list-disc space-y-0.5 pl-4 text-ink-2">
              {itinerary.notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </CardShell>
  )
}
