import { useState, useEffect } from 'react'
import { User, RefreshCw, Sparkles } from 'lucide-react'
import { fetchPreferences } from '../../api/client'
import { useChatStore } from '../../store/chatStore'

// 偏好分类定义
const CATEGORIES = [
  {
    key: 'travel',
    label: '旅行偏好',
    emoji: '🧳',
    color: 'var(--accent-light)',
    text: 'var(--accent)',
    keys: ['travel_preference', 'favorite_city', 'weather_preference', 'trip_style', 'home_location'],
  },
  {
    key: 'stay',
    label: '住宿出行',
    emoji: '🏨',
    color: 'light',
    text: 'blue',
    keys: ['hotel_brands', 'airlines', 'seat_preference'],
  },
  {
    key: 'life',
    label: '生活方式',
    emoji: '🍽️',
    color: 'light',
    text: 'green',
    keys: ['dietary', 'budget'],
  },
  {
    key: 'other',
    label: '其他',
    emoji: '📌',
    color: 'light',
    text: 'purple',
    keys: [], // 兜底：不属于上面的都归这里
  },
]

// 偏好类型 → 显示标签
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

// 各分类的 chip 样式（CSS 变量在 light/dark 下自动适配）
const CAT_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  travel:  { bg: 'var(--accent-light)', border: 'var(--accent)', text: 'var(--accent)' },
  stay:    { bg: '#dbeafe', border: '#93c5fd', text: '#2563eb' },
  life:    { bg: '#d1fae5', border: '#6ee7b7', text: '#059669' },
  other:   { bg: '#f3e8ff', border: '#c4b5fd', text: '#7c3aed' },
}

// 深色模式下的覆盖样式
const CAT_DARK_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  travel:  { bg: '#1e3a5f', border: '#60a5fa', text: '#93bbfd' },
  stay:    { bg: '#1e2a42', border: '#3b82f6', text: '#60a5fa' },
  life:    { bg: '#1a2e1a', border: '#10b981', text: '#34d399' },
  other:   { bg: '#2a1a3e', border: '#8b5cf6', text: '#a78bfa' },
}

function getCatStyle(catKey: string, isDark: boolean) {
  return isDark ? (CAT_DARK_STYLES[catKey] || CAT_DARK_STYLES.other) : (CAT_STYLES[catKey] || CAT_STYLES.other)
}

function categorize(entries: [string, unknown][]): { cat: typeof CATEGORIES[number]; items: [string, unknown][] }[] {
  const result: { cat: typeof CATEGORIES[number]; items: [string, unknown][] }[] = []
  const assigned = new Set<string>()

  for (const cat of CATEGORIES) {
    const items = entries.filter(([k]) => cat.keys.includes(k))
    if (items.length > 0) {
      result.push({ cat, items })
      items.forEach(([k]) => assigned.add(k))
    }
  }

  // 兜底：未分类的归入 "其他"
  const leftover = entries.filter(([k]) => !assigned.has(k))
  if (leftover.length > 0) {
    const otherCat = CATEGORIES[CATEGORIES.length - 1]
    result.push({ cat: otherCat, items: leftover })
  }

  return result
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join('、')
  return String(value)
}

export function PreferencePanel() {
  const userId = useChatStore((s) => s.userId)
  const [prefs, setPrefs] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await fetchPreferences(userId)
      setPrefs(data.preferences || {})
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [userId])

  useEffect(() => {
    const handler = () => { load() }
    window.addEventListener('preference-updated', handler)
    return () => window.removeEventListener('preference-updated', handler)
  }, [userId])

  const entries = Object.entries(prefs).filter(([, v]) => v)
  const grouped = categorize(entries)
  const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark')

  return (
    <div className="p-3">
      {/* 标题区 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs"
            style={{ background: 'var(--accent-light)', color: 'var(--accent)' }}>
            <User size={14} />
          </div>
          <div>
            <h4 className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>我的旅行画像</h4>
            {entries.length > 0 && (
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{entries.length} 项偏好</span>
            )}
          </div>
        </div>
        <button onClick={load} disabled={loading}
          className="p-1.5 rounded-lg transition-all hover:bg-[var(--bg-tertiary)] hover:scale-105 active:scale-95">
          <RefreshCw size={12} className={`text-[var(--text-muted)] ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* 内容 */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="space-y-2">
              <div className="skeleton h-3 w-16 rounded" />
              <div className="flex flex-wrap gap-1.5">
                <div className="skeleton h-7 w-20 rounded-full" />
                <div className="skeleton h-7 w-16 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="text-center py-6">
          <img src="/images/illustrations/no-preference.svg" alt="暂无偏好"
            className="w-24 h-auto mx-auto mb-3 opacity-70" />
          <p className="text-xs mb-1" style={{ color: 'var(--text-secondary)' }}>还没有记录偏好</p>
          <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
            在对话中告诉我你的喜好，我会记住
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map(({ cat, items }) => {
            const style = getCatStyle(cat.key, isDark)
            return (
              <div key={cat.key}>
                {/* 分类标题 */}
                <div className="flex items-center gap-1 mb-1.5">
                  <span className="text-xs">{cat.emoji}</span>
                  <span className="text-[10px] font-medium" style={{ color: 'var(--text-muted)' }}>
                    {cat.label}
                  </span>
                </div>
                {/* 标签 chips */}
                <div className="flex flex-wrap gap-1.5">
                  {items.map(([key, value]) => {
                    const meta = PREF_LABELS[key]
                    const icon = meta?.icon || '📌'
                    const display = formatValue(value)
                    return (
                      <div key={key}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all hover:scale-[1.03]"
                        style={{
                          backgroundColor: style.bg,
                          border: `1px solid ${style.border}`,
                          color: style.text,
                        }}>
                        <span className="text-xs">{icon}</span>
                        {display}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 底部引导 */}
      {entries.length > 0 && (
        <div className="mt-4 pt-3 text-center" style={{ borderTop: '1px solid var(--border-light)' }}>
          <p className="text-[10px] flex items-center justify-center gap-1" style={{ color: 'var(--text-muted)' }}>
            <Sparkles size={10} /> 在对话中告诉我更多偏好
          </p>
        </div>
      )}
    </div>
  )
}
