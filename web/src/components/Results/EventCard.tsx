import { AlertTriangle } from 'lucide-react'
import { CardShell } from './CardShell'

export function EventCard({ data }: { data: Record<string, unknown> }) {
  const origin = data.origin ? String(data.origin) : null
  const destination = data.destination ? String(data.destination) : null
  const startDate = data.start_date ? String(data.start_date) : null
  const endDate = data.end_date ? String(data.end_date) : null
  const purpose = data.trip_purpose ? String(data.trip_purpose) : null
  const summary = data.summary ? String(data.summary) : null
  const missing = Array.isArray(data.missing_info) ? (data.missing_info as string[]) : []

  return (
    <CardShell agentName="event_collection">
      <div className="border-b border-rule px-4 py-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / TRIP BRIEF</div>
        <h4 className="mt-1 text-[15px] font-semibold text-ink">事项信息</h4>
      </div>

      {origin && destination && (
        <div className="flex items-center gap-3 border-b border-rule px-4 py-4">
          <div className="min-w-0">
            <div className="font-mono text-[9px] tracking-[0.12em] text-ink-3">FROM</div>
            <div className="mt-1 truncate font-display text-[20px] text-ink">{origin}</div>
          </div>
          <div className="relative h-px flex-1 bg-rule-strong" aria-hidden="true">
            <span className="absolute -right-1 -top-1.5 text-[12px] text-accent">→</span>
          </div>
          <div className="min-w-0 text-right">
            <div className="font-mono text-[9px] tracking-[0.12em] text-ink-3">TO</div>
            <div className="mt-1 truncate font-display text-[20px] text-ink">{destination}</div>
          </div>
        </div>
      )}

      <div className="space-y-2 px-4 py-3 text-[12px]">
        {(origin && !destination) && (
          <div className="flex gap-3"><span className="w-12 shrink-0 text-ink-3">出发地</span><span className="text-ink">{origin}</span></div>
        )}
        {(destination && !origin) && (
          <div className="flex gap-3"><span className="w-12 shrink-0 text-ink-3">目的地</span><span className="text-ink">{destination}</span></div>
        )}
        {startDate && (
          <div className="flex gap-3">
            <span className="w-12 shrink-0 text-ink-3">日期</span>
            <span className="font-mono tabular text-ink">{startDate}{endDate ? ' – ' + endDate : ''}</span>
          </div>
        )}
        {purpose && (
          <div className="flex gap-3"><span className="w-12 shrink-0 text-ink-3">目的</span><span className="text-ink">{purpose}</span></div>
        )}
        {summary && <p className="border-t border-rule pt-2 leading-6 text-ink-2">{summary}</p>}

        {missing.length > 0 && (
          <div className="flex items-start gap-2 border border-warn/30 bg-warning-light p-2.5">
            <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
            <span className="leading-5 text-warn">缺少信息：{missing.join('、')}</span>
          </div>
        )}
      </div>
    </CardShell>
  )
}
