import { MapPin, Calendar, ArrowRight, AlertTriangle } from 'lucide-react'
import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'

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
      <div className="p-4 space-y-3">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="event_collection" size={16} /> 事项信息
        </h4>

        {/* Route visualization */}
        {origin && destination && (
          <div className="flex items-center gap-2 p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
            <div className="flex items-center gap-1.5 flex-1 min-w-0">
              <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: 'var(--accent-light)' }}>
                <MapPin size={12} className="text-[var(--accent)]" />
              </div>
              <span className="text-sm font-medium truncate">{origin}</span>
            </div>
            <div className="flex items-center gap-1 px-2">
              <div className="w-6 h-0.5 rounded-full" style={{ backgroundColor: 'var(--border)' }} />
              <ArrowRight size={14} className="text-[var(--accent)]" />
              <div className="w-6 h-0.5 rounded-full" style={{ backgroundColor: 'var(--border)' }} />
            </div>
            <div className="flex items-center gap-1.5 flex-1 min-w-0 justify-end">
              <span className="text-sm font-medium truncate">{destination}</span>
              <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: 'var(--success-light)' }}>
                <MapPin size={12} className="text-[var(--success)]" />
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-xs">
          {origin && !destination && (
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--text-muted)]">出发地:</span>
              <span className="font-medium">{origin}</span>
            </div>
          )}
          {destination && !origin && (
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--text-muted)]">目的地:</span>
              <span className="font-medium">{destination}</span>
            </div>
          )}
          {startDate && (
            <div className="flex items-center gap-1.5">
              <Calendar size={10} className="text-[var(--text-muted)]" />
              <span>{startDate}</span>
              {endDate && (
                <><ArrowRight size={10} /><span>{endDate}</span></>
              )}
            </div>
          )}
          {purpose && (
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--text-muted)]">目的:</span>
              <span>{purpose}</span>
            </div>
          )}
        </div>

        {missing.length > 0 && (
          <div className="flex items-start gap-2 p-2.5 rounded-xl text-xs"
            style={{ backgroundColor: 'var(--warning-light)' }}>
            <AlertTriangle size={14} className="text-[var(--warning)] flex-shrink-0 mt-0.5" />
            <span className="text-[var(--warning)]">缺少信息: {missing.join(', ')}</span>
          </div>
        )}
        {summary && <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{summary}</p>}
      </div>
    </CardShell>
  )
}
