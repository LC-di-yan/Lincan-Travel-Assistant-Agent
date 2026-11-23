import { useState, useEffect, useCallback } from 'react'
import { Hotel, Luggage, Pin, RefreshCw, Utensils, type LucideIcon } from 'lucide-react'
import { PreferenceTypeIcon } from '../Icons'
import { fetchPreferences } from '../../api/client'
import { useChatStore } from '../../store/chatStore'
import { preferenceGroup, preferenceLabel, type PreferenceGroup } from '../../utils/preferenceLabels'

const CATEGORIES: { key: PreferenceGroup; label: string; icon: LucideIcon }[] = [
  {
    key: 'travel',
    label: '旅行偏好',
    icon: Luggage,
  },
  {
    key: 'stay',
    label: '住宿出行',
    icon: Hotel,
  },
  {
    key: 'life',
    label: '生活方式',
    icon: Utensils,
  },
  {
    key: 'other',
    label: '其他',
    icon: Pin,
  },
]

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
  return CATEGORIES.map((cat) => ({ cat, items: entries.filter(([key]) => preferenceGroup(key) === cat.key) }))
    .filter(({ items }) => items.length > 0)
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join('、')
  return String(value)
}

export function PreferencePanel({ personalAvailable = false }: { personalAvailable?: boolean }) {
  const userId = useChatStore((s) => s.userId)
  const sessionId = useChatStore((s) => s.sessionId)
  const [prefs, setPrefs] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => fetchPreferences(userId, sessionId)
    .then((data) => setPrefs(data.preferences || {}))
    .catch(() => { /* 保留上次加载的数据 */ })
    .finally(() => setLoading(false)), [userId, sessionId])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    const handler = () => { load() }
    window.addEventListener('preference-updated', handler)
    return () => window.removeEventListener('preference-updated', handler)
  }, [load])

  return <>
    {personalAvailable && <a href="#/personal/preferences" className="mx-4 mt-2 inline-flex min-h-11 items-center text-xs font-semibold text-route underline">管理规划授权</a>}
    <PreferencePanelContent preferences={prefs} loading={loading} onRefresh={() => { setLoading(true); void load() }} />
  </>
}

export function PreferencePanelContent({ preferences, loading, onRefresh }: {
  preferences: Record<string, unknown>
  loading: boolean
  onRefresh: () => void
}) {
  const entries = Object.entries(preferences).filter(([, v]) => v)
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
          onClick={onRefresh}
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
                  <cat.icon size={12} strokeWidth={1.5} aria-hidden="true" />
                  <span className="font-mono text-[9px] tracking-[0.14em] text-ink-3">{cat.label}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {items.map(([key, value]) => {
                    const label = preferenceLabel(key)
                    return (
                      <span
                        key={key}
                        title={label}
                        aria-label={label + '：' + formatValue(value)}
                        className="inline-flex items-center gap-1 rounded-[2px] border px-2 py-1 text-[10px]"
                        style={{ backgroundColor: style.bg, borderColor: style.border, color: style.text }}
                      >
                        <PreferenceTypeIcon kind={key} size={12} className="shrink-0" />
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
