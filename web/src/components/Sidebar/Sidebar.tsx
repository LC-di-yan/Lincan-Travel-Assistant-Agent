import { useState, useEffect, lazy, Suspense } from 'react'
import { Brain, Heart, MapPin, Puzzle, Receipt } from 'lucide-react'
import { useChatStore } from '../../store/chatStore'

const IntentPanel = lazy(() => import('./IntentPanel').then((m) => ({ default: m.IntentPanel })))
const PreferencePanel = lazy(() => import('./PreferencePanel').then((m) => ({ default: m.PreferencePanel })))
const HistoryPanel = lazy(() => import('./HistoryPanel').then((m) => ({ default: m.HistoryPanel })))
const PluginPanel = lazy(() => import('./PluginPanel').then((m) => ({ default: m.PluginPanel })))
const ExpensePanel = lazy(() => import('./ExpensePanel').then((m) => ({ default: m.ExpensePanel })))

const tabs = [
  { key: 'intent', label: '意图', icon: Brain },
  { key: 'prefs', label: '偏好', icon: Heart },
  { key: 'history', label: '历史', icon: MapPin },
  { key: 'expenses', label: '费用', icon: Receipt },
  { key: 'plugins', label: '插件', icon: Puzzle },
] as const

type TabKey = typeof tabs[number]['key']

export function Sidebar() {
  const [tab, setTab] = useState<TabKey>('intent')
  const isProcessing = useChatStore((s) => s.isProcessing)

  useEffect(() => {
    if (isProcessing) setTab('intent')
  }, [isProcessing])

  return (
    <div className="flex h-full flex-col bg-paper">
      <div role="tablist" aria-label="行程档案" className="flex gap-4 border-b border-rule px-3 pt-3">
        {tabs.map((t) => {
          const active = tab === t.key
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              id={'tab-' + t.key}
              aria-selected={active}
              aria-controls={'panel-' + t.key}
              onClick={() => setTab(t.key)}
              onKeyDown={(e) => {
                if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
                e.preventDefault()
                const idx = tabs.findIndex((x) => x.key === tab)
                const next = tabs[(idx + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]
                setTab(next.key)
                document.getElementById('tab-' + next.key)?.focus()
              }}
              className={
                'flex items-center gap-1 pb-2.5 text-[11px] font-medium transition-colors ' +
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

      <div role="tabpanel" id={'panel-' + tab} aria-labelledby={'tab-' + tab} className="min-h-0 flex-1 overflow-y-auto">
        <Suspense fallback={<div className="p-4 text-[11px] text-ink-3">加载中…</div>}>
          {tab === 'intent' && <IntentPanel />}
          {tab === 'prefs' && <PreferencePanel />}
          {tab === 'history' && <HistoryPanel />}
          {tab === 'expenses' && <ExpensePanel />}
          {tab === 'plugins' && <PluginPanel />}
        </Suspense>
      </div>
    </div>
  )
}
