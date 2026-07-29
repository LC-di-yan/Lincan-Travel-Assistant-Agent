import { useState, useEffect } from 'react'
import { Puzzle } from 'lucide-react'

interface Plugin {
  name: string
  enabled: boolean
  loaded: boolean
}

export function PluginPanel() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/plugins')
      .then((r) => r.json())
      .then((d) => setPlugins(d.plugins || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const toggle = async (name: string, enabled: boolean) => {
    try {
      const res = await fetch('/api/plugins', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, enabled }),
      })
      const data = await res.json()
      setPlugins(data.plugins || [])
    } catch {}
  }

  if (loading) {
    return (
      <div className="p-3 space-y-1.5">
        <div className="flex items-center gap-1.5 mb-2">
          <div className="skeleton h-3 w-16" />
          <div className="skeleton h-3 w-8 ml-auto" />
        </div>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-center gap-2 px-3 py-2.5 rounded-xl"
            style={{ backgroundColor: 'var(--bg-secondary)' }}>
            <div className="flex-1">
              <div className="skeleton h-3 w-16 mb-1.5" />
              <div className="skeleton h-2.5 w-24" />
            </div>
            <div className="skeleton w-9 h-5 rounded-full" />
          </div>
        ))}
      </div>
    )
  }

  const friendlyNames: Record<string, string> = {
    'ask-question': '政策问答',
    'event-collection': '事项收集',
    'memory-query': '记忆查询',
    'plan-trip': '行程规划',
    'preference': '偏好管理',
    'query-info': '信息查询',
    'expense-tracker': '费用记录',
    'currency-converter': '汇率转换',
  }

  return (
    <div className="p-3 space-y-1.5">
      <div className="flex items-center gap-1.5 mb-2">
        <Puzzle size={14} className="text-[var(--accent)]" />
        <span className="text-xs font-semibold">插件管理</span>
        <span className="text-xs text-[var(--text-muted)] ml-auto">{plugins.filter((p) => p.enabled).length}/{plugins.length}</span>
      </div>

      {plugins.map((plugin) => (
        <div
          key={plugin.name}
          className="flex items-center gap-2 px-3 py-2.5 rounded-xl transition-all card-hover"
          style={{ backgroundColor: 'var(--bg-secondary)' }}
        >
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium truncate">
              {friendlyNames[plugin.name] || plugin.name}
            </div>
            <div className="text-[10px] text-[var(--text-muted)] truncate">{plugin.name}</div>
          </div>

          <div className="flex items-center gap-2">
            {plugin.loaded && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}>
                已加载
              </span>
            )}
            <button
              onClick={() => toggle(plugin.name, !plugin.enabled)}
              className="relative w-9 h-5 rounded-full transition-colors duration-200"
              style={{
                backgroundColor: plugin.enabled ? 'var(--accent)' : 'var(--border)',
              }}
            >
              <div
                className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200"
                style={{
                  transform: plugin.enabled ? 'translateX(18px)' : 'translateX(2px)',
                }}
              />
            </button>
          </div>
        </div>
      ))}

      <p className="text-[10px] text-[var(--text-muted)] mt-2 px-1">
        禁用的插件不会被意图识别调度
      </p>
    </div>
  )
}
