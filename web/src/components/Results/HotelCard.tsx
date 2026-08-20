import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'
import type { HotelItem } from '../../api/types'
import { Star, MapPin, ExternalLink } from 'lucide-react'

function amapLink(location: string, name: string): string {
  if (!location) return '#'
  return `https://uri.amap.com/marker?position=${location}&name=${encodeURIComponent(name)}`
}

function HotelRow({ hotel }: { hotel: HotelItem }) {
  const rating = Number(hotel.rating)
  const costDisplay = hotel.cost ? formatCost(hotel.cost) : ''
  const dist = Number(hotel.distance)
  const distDisplay = dist > 0 ? formatDistance(dist) : ''

  return (
    <a
      href={amapLink(hotel.location, hotel.name)}
      target="_blank"
      rel="noopener noreferrer"
      className="flex gap-3 p-3 rounded-xl transition-colors hover:brightness-95 block"
      style={{ backgroundColor: 'var(--bg-secondary)' }}
    >
      {/* Photo */}
      <div
        className="w-16 h-16 rounded-xl shrink-0 flex items-center justify-center text-xs text-[var(--text-muted)]"
        style={{
          backgroundColor: 'var(--bg-primary)',
          backgroundImage: hotel.photo ? `url(${hotel.photo})` : undefined,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      >
        {!hotel.photo && 'No img'}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-semibold truncate">{hotel.name}</span>
          {rating > 0 && (
            <span className="flex items-center gap-0.5 text-xs font-medium shrink-0"
              style={{ color: 'var(--accent)' }}>
              <Star size={11} fill="currentColor" /> {hotel.rating}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-xs text-[var(--text-muted)] mt-0.5">
          <MapPin size={11} className="shrink-0" />
          <span className="truncate">{hotel.address || '-'}</span>
        </div>
        <div className="flex items-center gap-3 mt-1 text-xs">
          {costDisplay && (
            <span className="font-medium" style={{ color: 'var(--accent)' }}>{costDisplay}</span>
          )}
          {distDisplay && (
            <span className="text-[var(--text-muted)]">{distDisplay}</span>
          )}
        </div>
      </div>
    </a>
  )
}

function formatCost(cost: string): string {
  if (typeof cost !== 'string') return ''
  const cleaned = cost.replace(/[￥¥\[\]"]/g, '')
  if (!cleaned) return ''
  return `¥${cleaned}`
}

function formatDistance(meters: number): string {
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)}km`
  return `${Math.round(meters)}m`
}

export function HotelCard({ data }: { data: Record<string, unknown> }) {
  const results = (data.results || data) as Record<string, unknown>
  const city = results.city as string || ''
  const keyword = results.keyword as string || '酒店'
  const count = results.count as number || 0
  const countDisplay = count >= 600 ? '共600+家' : count > 0 ? `共${count}家` : ''
  const summary = results.summary as string || ''
  const hotels = (results.hotels || []) as HotelItem[]
  const sources = (results.sources || data.sources) as { title: string; url: string }[] | undefined

  return (
    <CardShell agentName="hotel_search">
      <div className="p-4 space-y-3">
        {/* Header */}
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="hotel_search" size={16} />
          {city}{keyword}搜索
          {countDisplay && (
            <span className="text-xs text-[var(--text-muted)] font-normal">{countDisplay}</span>
          )}
        </h4>

        {/* Summary */}
        {summary && (
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{summary}</p>
        )}

        {/* Hotel List */}
        {hotels.length > 0 && (
          <div className="space-y-2 max-h-[480px] overflow-y-auto">
            {hotels.map((h) => (
              <HotelRow key={h.id} hotel={h} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {count === 0 && (
          <div className="py-6 text-center text-sm text-[var(--text-muted)]">
            未找到相关住宿信息，请尝试更换城市或关键词
          </div>
        )}

        {/* Error state */}
        {data.error != null && (
          <p className="text-sm text-[var(--error)]">{String(data.error)}</p>
        )}

        {/* Source */}
        {sources && sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {sources.map((s, i) => (
              <a key={i} href={s.url} target="_blank" rel="noopener noreferrer"
                className="text-xs px-2.5 py-1 rounded-full flex items-center gap-1 transition-all hover:shadow-sm"
                style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}>
                <ExternalLink size={10} /> {s.title}
              </a>
            ))}
          </div>
        )}
      </div>
    </CardShell>
  )
}
