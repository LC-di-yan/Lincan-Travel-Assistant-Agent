import { useState, useEffect } from 'react'
import { RefreshCw } from 'lucide-react'
import { fetchPreferences } from '../../api/client'
import { useChatStore } from '../../store/chatStore'

const CATEGORIES = [
  {
    key: 'travel',
    label: '旅行偏好',
    emoji: '🧳',
    keys: ['travel_preference', 'favorite_city', 'weather_preference', 'trip_style', 'home_location'],
  },
  {
    key: 'stay',
    label: '住宿出行',
    emoji: '🏨',
    keys: ['hotel_brands', 'airlines', 'seat_preference'],
  },
  {
    key: 'life',
    label: '生活方式',
    emoji: '🍽️',
    keys: ['dietary', 'budget'],
  },
  {
    key: 'other',
    label: '其他',
    emoji: '📌',
    keys: [],
  },
]

const PREF_LABELS: Record<string, { label: string; icon: string }> = {
  hotel_brands: { label: '酒店', icon: '🏨' },
  airlines: { label: '航空', icon: '✈️' },
  seat_preference: { label: '座位', icon: '💺' },
  home_location: { label: '常驻地', icon: '🏠' },
  dietary: { label: '饮食', icon: '🍽️' },
  budget: { label: '预算', icon: '💰' },
  travel_preference: { label: '旅行方式', icon: '🧳' },
  favorite_city: { label: '心仪城市', icon: '❤️' },
  weather_preference: { label: '天气偏好', icon: '🌤️' },
  trip_style: { label: '风格', icon: '✨' },
}

const CAT_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  travel: { bg: 'var(--accent-tint)', border: 'var(--accent)', text: 'var(--accent)' },
  stay: { bg: 'var(--route-tint)', border: 'var(--route)', text: 'var(--route)' },
  life: { bg: 'var(--success-light)', border: 'var(--success)', text: 'var(--success)' },
  other: { bg: 'var(--warning-light)', border: 'var(--warning)', text: 'var(--warning)' },
}

function getCatStyle(catKey: string) {
  return CAT_STYLES[catKey] || CAT_STYLES.other
}

function categorize(entries: [string, unknown][]) {
  const result: { cat: typeof CATEGORIES[number]; items: [string, unknown][] }[] = []
  const assigned = new Set<string>()

  for (const cat of CATEGORIES) {
    const items = entries.filter(([k]) => cat.keys.includes(k))
    if (items.length > 0) {
      result.push({ cat, items })
      items.forEach(([k]) => assigned.add(k))
    }
  }

  const leftover = entries.filter(([k]) => !assigned.has(k))
  if (leftover.length > 0) {
    result.push({ cat: CATEGORIES[CATEGORIES.length - 1], items: leftover })
  }

  return result
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join('、')
  return String(value)
}

export function PreferencePanel() {
  const userId = useChatStore((s) => s.userId)
  const sessionId = useChatStore((s) => s.sessionId)
  const [prefs, setPrefs] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await fetchPreferences(userId, sessionId)
      setPrefs(data.preferences || {})
    } catch {
      /* keep last state */
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [userId, sessionId])

  useEffect(() => {
    const handler = () => { load() }
    window.addEventListener('preference-updated', handler)
    return () => window.removeEventListener('preference-updated', handler)
  }, [userId, sessionId])

  const entries = Object.entries(prefs).filter(([, v]) => v)
  const grouped = categorize(entries)

  return (
    <div className="p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="font-mono text-[9px] tracking-[0.16em] text-accent">ALIGO / PREFERENCES</div>
          <h4 className="mt-1 text-[13px] font-semibold text-ink">我的旅行画像</h4>
          {entries.length > 0 && (
            <div className="mt-0.5 text-[10px] text-ink-3">{entries.length} 项偏好</div>
          )}
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          aria-label="刷新偏好"
          title="刷新偏好"
          className="flex h-10 w-10 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
        </button>
      </div>

      {loading ? (
        <div className="space-y-4 pt-1">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i}>
              <div className="skeleton mb-2 h-2.5 w-16" />
              <div className="flex flex-wrap gap-1.5">
                <div className="skeleton h-6 w-20" />
                <div className="skeleton h-6 w-16" />
              </div>
            </div>
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="py-8 text-center">
          <p className="text-[12px] text-ink-2">还没有记录偏好</p>
          <p className="mt-1 text-[10px] leading-5 text-ink-3">在对话里告诉我你的喜好，我会记住</p>
        </div>
      ) : (
        <div>
          {grouped.map(({ cat, items }) => {
            const style = getCatStyle(cat.key)
            return (
              <section key={cat.key} className="border-b border-rule py-3 last:border-0">
                <div className="mb-2 flex items-center gap-1.5">
                  <span className="text-[11px]" aria-hidden="true">{cat.emoji}</span>
                  <span className="font-mono text-[9px] tracking-[0.14em] text-ink-3">{cat.label}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {items.map(([key, value]) => {
                    const meta = PREF_LABELS[key]
                    return (
                      <span
                        key={key}
                        className="inline-flex items-center gap-1 rounded-[2px] border px-2 py-1 text-[10px]"
                        style={{ backgroundColor: style.bg, borderColor: style.border, color: style.text }}
                      >
                        <span aria-hidden="true">{meta?.icon || '📌'}</span>
                        {formatValue(value)}
                      </span>
                    )
                  })}
                </div>
              </section>
            )
          })}
          <div className="pt-3 text-center">
            <p className="text-[10px] text-ink-3">在对话里告诉我更多偏好</p>
          </div>
        </div>
      )}
    </div>
  )
}
