import { useState, useEffect } from 'react'
import { MapPin, Calendar, RefreshCw, TrendingUp } from 'lucide-react'
import { fetchHistory } from '../../api/client'
import { useChatStore } from '../../store/chatStore'
import type { TripRecord, FrequentDestination } from '../../api/types'

export function HistoryPanel() {
  const userId = useChatStore((s) => s.userId)
  const [trips, setTrips] = useState<TripRecord[]>([])
  const [frequent, setFrequent] = useState<FrequentDestination[]>([])
  const [stats, setStats] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await fetchHistory(userId)
      setTrips(data.trips || [])
      setFrequent(data.frequent_destinations || [])
      setStats(data.statistics || {})
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [userId])

  return (
    <div className="p-3">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold text-[var(--text-muted)] flex items-center gap-1">
          <MapPin size={10} /> 历史行程
        </h4>
        <button onClick={load} disabled={loading}
          className="p-1.5 rounded-lg transition-all hover:bg-[var(--bg-tertiary)] hover:scale-105 active:scale-95">
          <RefreshCw size={12} className={`text-[var(--text-muted)] ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="p-2.5 rounded-xl text-center" style={{ backgroundColor: 'var(--bg-secondary)' }}>
          <div className="text-lg font-bold text-[var(--accent)]">{(stats.total_trips as number) || 0}</div>
          <div className="text-xs text-[var(--text-muted)]">总行程</div>
        </div>
        <div className="p-2.5 rounded-xl text-center" style={{ backgroundColor: 'var(--bg-secondary)' }}>
          <div className="text-lg font-bold text-[var(--success)]">{(stats.total_messages as number) || 0}</div>
          <div className="text-xs text-[var(--text-muted)]">总消息</div>
        </div>
      </div>

      {frequent.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs text-[var(--text-muted)] mb-2 flex items-center gap-1">
            <TrendingUp size={10} /> 常去城市
          </h5>
          <div className="flex flex-wrap gap-1.5">
            {frequent.map((f, i) => (
              <span key={i} className="text-xs px-2.5 py-1 rounded-full font-medium"
                style={{ backgroundColor: 'var(--success-light)', color: 'var(--success)' }}>
                {f.city} ({f.count})
              </span>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="relative pl-6 pb-2">
              <div className="absolute left-1.5 top-1 bottom-0 w-0.5" style={{ backgroundColor: 'var(--border)' }} />
              <div className="absolute left-0.5 top-1.5 w-3 h-3 rounded-full" style={{ backgroundColor: 'var(--bg-tertiary)' }} />
              <div className="skeleton h-3 w-24 mb-1.5" />
              <div className="skeleton h-3 w-32" />
            </div>
          ))}
        </div>
      ) : trips.length === 0 ? (
        <div className="text-center py-6">
          <img src="/images/illustrations/no-history.svg" alt="暂无记录" className="w-28 h-auto mx-auto mb-3 opacity-80" />
          <p className="text-xs text-[var(--text-muted)]">暂无行程记录</p>
        </div>
      ) : (
        <div className="space-y-2">
          {trips.map((trip, i) => (
            <div key={i} className="relative pl-6 pb-2">
              <div className="absolute left-1.5 top-1 bottom-0 w-0.5" style={{ backgroundColor: 'var(--border)' }} />
              <div className="absolute left-0.5 top-1.5 w-3 h-3 rounded-full border-2"
                style={{ borderColor: 'var(--accent)', backgroundColor: 'var(--bg-primary)' }} />
              <div className="text-xs">
                <div className="font-medium">{trip.origin} → {trip.destination}</div>
                <div className="flex items-center gap-1 text-[var(--text-muted)]">
                  <Calendar size={10} />
                  {trip.start_date} {trip.end_date ? `~ ${trip.end_date}` : ''}
                </div>
                {trip.purpose && <span className="text-[var(--text-secondary)]">{trip.purpose}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
