import { useId, useState, lazy, Suspense } from 'react'
import { Brain, Heart, MapPin, Puzzle, Receipt } from 'lucide-react'
import { useAgentActivity } from '../../hooks/useAgentActivity'

const IntentPanel = lazy(() => import('./IntentPanel').then((m) => ({ default: m.IntentPanel })))
const PreferencePanel = lazy(() => import('./PreferencePanel').then((m) => ({ default: m.PreferencePanel })))
const HistoryPanel = lazy(() => import('./HistoryPanel').then((m) => ({ default: m.HistoryPanel })))
const PluginPanel = lazy(() => import('./PluginPanel').then((m) => ({ default: m.PluginPanel })))
const ExpensePanel = lazy(() => import('./ExpensePanel').then((m) => ({ default: m.ExpensePanel })))

const tabs = [
  { key: 'intent', label: '协作', icon: Brain },
  { key: 'prefs', label: '偏好', icon: Heart },
  { key: 'history', label: '行程', icon: MapPin },
  { key: 'expenses', label: '费用', icon: Receipt },
  { key: 'plugins', label: '插件', icon: Puzzle },
] as const

type TabKey = typeof tabs[number]['key']

export function Sidebar({ personalAvailable = false }: { personalAvailable?: boolean }) {
  const [tab, setTab] = useState<TabKey>('intent')
  const id = useId()
  const { live } = useAgentActivity()

  return (
    <div className="flex h-full flex-col bg-paper">
      <div role="tablist" aria-label="行程档案" className="grid grid-cols-5 border-b border-rule px-2 pt-1">
        {tabs.map((t) => {
          const active = tab === t.key
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              id={id + '-tab-' + t.key}
              tabIndex={active ? 0 : -1}
              aria-selected={active}
              aria-controls={active ? id + '-panel-' + t.key : undefined}
              onClick={() => setTab(t.key)}
              onKeyDown={(e) => {
                if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
                e.preventDefault()
                const idx = tabs.findIndex((x) => x.key === tab)
                const next = tabs[(idx + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]
                setTab(next.key)
                document.getElementById(id + '-tab-' + next.key)?.focus()
              }}
              className={
                'flex min-h-11 items-center justify-center gap-1 text-xs font-medium transition-colors ' +
                (active
                  ? 'border-b-2 border-accent text-ink'
                  : 'border-b-2 border-transparent text-ink-3 hover:text-ink')
              }
            >
              <t.icon size={12} aria-hidden="true" />
              {t.label}
            </button>
          )
        })}
      </div>

      {live && tab !== 'intent' && <p className="border-b border-rule bg-route-tint px-3 py-2 text-xs text-route">本轮协作仍在进行。可切换到「协作」查看进度。</p>}
      <div role="tabpanel" id={id + '-panel-' + tab} aria-labelledby={id + '-tab-' + tab} className="min-h-0 flex-1 overflow-y-auto">
        <Suspense fallback={<div className="p-4 text-[11px] text-ink-3">加载中…</div>}>
          {tab === 'intent' && <IntentPanel />}
          {tab === 'prefs' && <PreferencePanel personalAvailable={personalAvailable} />}
          {tab === 'history' && <HistoryPanel personalAvailable={personalAvailable} />}
          {tab === 'expenses' && <ExpensePanel personalAvailable={personalAvailable} />}
          {tab === 'plugins' && <PluginPanel />}
        </Suspense>
      </div>
    </div>
  )
}
