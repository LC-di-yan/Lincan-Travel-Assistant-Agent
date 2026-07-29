import { useState, useEffect } from 'react'
import { Brain, Heart, MapPin, Puzzle, Receipt } from 'lucide-react'
import { IntentPanel } from './IntentPanel'
import { PreferencePanel } from './PreferencePanel'
import { HistoryPanel } from './HistoryPanel'
import { PluginPanel } from './PluginPanel'
import { ExpensePanel } from './ExpensePanel'
import { useChatStore } from '../../store/chatStore'

const tabs = [
  { key: 'intent', label: '意图', icon: Brain },
  { key: 'prefs', label: '偏好', icon: Heart },
  { key: 'history', label: '历史', icon: MapPin },
  { key: 'expenses', label: '费用', icon: Receipt },
  { key: 'plugins', label: '插件', icon: Puzzle },
] as const

export function Sidebar() {
  const [tab, setTab] = useState<'intent' | 'prefs' | 'history' | 'expenses' | 'plugins'>('intent')
  const isProcessing = useChatStore((s) => s.isProcessing)

  useEffect(() => {
    if (isProcessing) setTab('intent')
  }, [isProcessing])

  return (
    <div className="flex flex-col h-full">
      <div className="flex p-1.5 gap-0.5" style={{ borderBottom: '1px solid var(--border)' }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 flex items-center justify-center gap-1 py-2 text-xs font-medium rounded-lg transition-all duration-200 ${
              tab === t.key
                ? 'text-[var(--accent)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
            style={tab === t.key ? { backgroundColor: 'var(--accent-light)' } : {}}
          >
            <t.icon size={12} />
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        <div style={{ display: tab === 'intent' ? 'block' : 'none' }}><IntentPanel /></div>
        <div style={{ display: tab === 'prefs' ? 'block' : 'none' }}><PreferencePanel /></div>
        <div style={{ display: tab === 'history' ? 'block' : 'none' }}><HistoryPanel /></div>
        <div style={{ display: tab === 'expenses' ? 'block' : 'none' }}><ExpensePanel /></div>
        <div style={{ display: tab === 'plugins' ? 'block' : 'none' }}><PluginPanel /></div>
      </div>
    </div>
  )
}
