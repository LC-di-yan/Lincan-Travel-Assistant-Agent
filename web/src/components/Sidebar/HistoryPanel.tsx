import { useState, useEffect } from 'react'
import { RefreshCw } from 'lucide-react'
import { fetchHistory } from '../../api/client'
import { useChatStore } from '../../store/chatStore'
import type { TripRecord, FrequentDestination } from '../../api/types'

export function HistoryPanel() {
  const userId = useChatStore((s) => s.userId)
  const sessionId = useChatStore((s) => s.sessionId)
  const [trips, setTrips] = useState<TripRecord[]>([])
  const [frequent, setFrequent] = useState<FrequentDestination[]>([])
  const [stats, setStats] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await fetchHistory(userId, sessionId)
      setTrips(data.trips || [])
      setFrequent(data.frequent_destinations || [])
      setStats(data.statistics || {})
    } catch {
      /* keep last state */
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [userId, sessionId])

  return (
    <div className="p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="font-mono text-[9px] tracking-[0.16em] text-accent">ALIGO / HISTORY</div>
          <h4 className="mt-1 text-[13px] font-semibold text-ink">历史行程</h4>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          aria-label="刷新历史"
          title="刷新历史"
          className="flex h-10 w-10 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
        </button>
      </div>

      <div className="grid grid-cols-2 border-y border-rule">
        <div className="border-r border-rule py-2.5 text-center">
          <div className="font-mono text-[18px] font-semibold tabular text-accent">{(stats.total_trips as number) || 0}</div>
          <div className="mt-0.5 text-[10px] text-ink-3">总行程</div>
        </div>
        <div className="py-2.5 text-center">
          <div className="font-mono text-[18px] font-semibold tabular text-ink">{(stats.total_messages as number) || 0}</div>
          <div className="mt-0.5 text-[10px] text-ink-3">总消息</div>
        </div>
      </div>

      {frequent.length > 0 && (
        <div className="border-b border-rule py-3">
          <div className="mb-2 font-mono text-[9px] tracking-[0.14em] text-ink-3">FREQUENT</div>
          <div className="flex flex-wrap gap-1.5">
            {frequent.map((f, i) => (
              <span key={i} className="rounded-[2px] border border-rule px-2 py-1 text-[10px] text-ink-2">
                {f.city}<span className="ml-1 font-mono text-ink-3">{f.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-3 pt-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i}>
              <div className="skeleton mb-1.5 h-3 w-28" />
              <div className="skeleton h-3 w-40" />
            </div>
          ))}
        </div>
      ) : trips.length === 0 ? (
        <div className="py-8 text-center">
          <p className="text-[12px] text-ink-2">暂无行程记录</p>
          <p className="mt-1 text-[10px] text-ink-3">完成一次行程后会自动归档</p>
        </div>
      ) : (
        <div>
          {trips.map((trip, i) => (
            <div key={i} className="flex items-start gap-2 border-b border-rule py-2.5 text-[11px] last:border-0">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-ink">{trip.origin} → {trip.destination}</span>
                  <span className="shrink-0 font-mono text-[9px] tabular text-ink-3">{trip.start_date}</span>
                </div>
                {(trip.end_date || trip.purpose) && (
                  <div className="mt-0.5 flex items-baseline justify-between gap-2">
                    <span className="truncate text-[10px] text-ink-3">{trip.purpose}</span>
                    {trip.end_date && <span className="shrink-0 font-mono text-[9px] tabular text-ink-3">– {trip.end_date}</span>}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
