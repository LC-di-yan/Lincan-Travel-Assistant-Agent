import { useState } from 'react'
import { Star, MapPin, ExternalLink } from 'lucide-react'
import { CardShell } from './CardShell'

export interface PlaceItem {
  id: string
  name: string
  address: string
  rating: string
  cost: string
  distance: string
  photo: string
  location: string
}

function amapLink(location: string, name: string): string {
  if (!location) return '#'
  return 'https://uri.amap.com/marker?position=' + location + '&name=' + encodeURIComponent(name)
}

function formatCost(cost: string): string {
  if (typeof cost !== 'string') return ''
  const cleaned = cost.replace(/[￥¥\[\]"]/g, '')
  if (!cleaned) return ''
  return '¥' + cleaned
}

function formatDistance(meters: number): string {
  if (meters >= 1000) return (meters / 1000).toFixed(1) + 'km'
  return Math.round(meters) + 'm'
}

function PlaceRow({ item }: { item: PlaceItem }) {
  const rating = Number(item.rating)
  const costDisplay = item.cost ? formatCost(item.cost) : ''
  const dist = Number(item.distance)
  const distDisplay = dist > 0 ? formatDistance(dist) : ''

  return (
    <a
      href={amapLink(item.location, item.name)}
      target="_blank"
      rel="noopener noreferrer"
      className="flex gap-3 border-b border-rule py-2.5 last:border-0 hover:bg-paper-sunken"
    >
      <div
        className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[2px] border border-rule bg-paper-sunken bg-cover bg-center"
        style={{ backgroundImage: item.photo ? 'url(' + item.photo + ')' : undefined }}
        aria-hidden="true"
      >
        {!item.photo && <MapPin size={14} className="text-ink-3" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-[13px] font-semibold text-ink">{item.name}</span>
          {rating > 0 && (
            <span className="flex shrink-0 items-center gap-0.5 font-mono text-[11px] tabular text-accent">
              <Star size={10} fill="currentColor" aria-hidden="true" /> {item.rating}
            </span>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-1 text-[11px] text-ink-3">
          <MapPin size={10} className="shrink-0" aria-hidden="true" />
          <span className="truncate">{item.address || '-'}</span>
        </div>
        <div className="mt-1 flex items-center gap-3 text-[11px]">
          {costDisplay && <span className="font-mono font-semibold tabular text-accent">{costDisplay}</span>}
          {distDisplay && <span className="text-ink-3">{distDisplay}</span>}
        </div>
      </div>
    </a>
  )
}

export function PlaceListCard({
  agentName,
  eyebrow,
  city,
  keyword,
  unit,
  summary,
  items,
  count,
  sources,
  emptyText,
  error,
}: {
  agentName: string
  eyebrow: string
  city: string
  keyword: string
  unit: string
  summary: string
  items: PlaceItem[]
  count: number
  sources?: { title: string; url: string }[]
  emptyText: string
  error?: unknown
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? items : items.slice(0, 5)
  const countDisplay = count >= 600 ? '共 600+ ' + unit : count > 0 ? '共 ' + count + ' ' + unit : ''
  const titleKeyword = city && keyword.startsWith(city) ? keyword : city + keyword

  return (
    <CardShell agentName={agentName}>
      <div className="border-b border-rule px-4 py-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-accent">{eyebrow}</div>
        <h4 className="mt-1 text-[15px] font-semibold text-ink">
          {titleKeyword}搜索
          {countDisplay && <span className="ml-2 text-[11px] font-normal text-ink-3">{countDisplay}</span>}
        </h4>
      </div>

      <div className="px-4 py-3">
        {summary && <p className="mb-2 text-[12px] leading-6 text-ink-2">{summary}</p>}

        {items.length > 0 && (
          <div>
            {shown.map((item) => <PlaceRow key={item.id} item={item} />)}
            {items.length > 5 && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="mt-2 text-[11px] font-semibold text-accent hover:underline"
              >
                {expanded ? '收起' : '查看全部 ' + items.length + ' ' + unit}
              </button>
            )}
          </div>
        )}

        {count === 0 && !items.length && (
          <div className="py-6 text-center text-[12px] text-ink-3">{emptyText}</div>
        )}

        {error != null && <p className="text-[12px] text-err">{String(error)}</p>}

        {sources && sources.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-rule pt-2.5">
            {sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 rounded-[2px] border border-rule px-2 py-1 text-[10px] text-ink-3 hover:text-accent"
              >
                <ExternalLink size={9} aria-hidden="true" /> {s.title}
              </a>
            ))}
          </div>
        )}
      </div>
    </CardShell>
  )
}
