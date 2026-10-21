import { useState, useEffect } from 'react'

interface Plugin {
  name: string
  enabled: boolean
  loaded: boolean
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
  'hotel-search': '酒店搜索',
  'place-search': '地点搜索',
  'train-ticket': '火车票',
  'translation': '翻译',
  'visa-info': '签证信息',
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
    } catch {
      /* keep last state */
    }
  }

  if (loading) {
    return (
      <div className="p-4">
        <div className="skeleton mb-2 h-3 w-20" />
        <div className="skeleton mb-4 h-3 w-12" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border-b border-rule py-3">
            <div className="skeleton mb-1.5 h-3 w-20" />
            <div className="skeleton h-2.5 w-28" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="font-mono text-[9px] tracking-[0.16em] text-accent">ALIGO / PLUGINS</div>
          <h4 className="mt-1 text-[13px] font-semibold text-ink">插件管理</h4>
        </div>
        <span className="font-mono text-[10px] tabular text-ink-3">
          {plugins.filter((p) => p.enabled).length}/{plugins.length}
        </span>
      </div>

      <div>
        {plugins.map((plugin) => (
          <div key={plugin.name} className="flex items-center gap-3 border-b border-rule py-2.5 last:border-0">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-[12px] font-medium text-ink">
                  {friendlyNames[plugin.name] || plugin.name}
                </span>
                {plugin.loaded && (
                  <span className="shrink-0 rounded-[2px] border border-rule px-1 py-0.5 text-[8px] tracking-[0.04em] text-ink-3">
                    已加载
                  </span>
                )}
              </div>
              <div className="mt-0.5 truncate font-mono text-[9px] text-ink-3">{plugin.name}</div>
            </div>

            <button
              type="button"
              role="switch"
              aria-checked={plugin.enabled}
              aria-label={(plugin.enabled ? '禁用 ' : '启用 ') + (friendlyNames[plugin.name] || plugin.name)}
              onClick={() => toggle(plugin.name, !plugin.enabled)}
              className="relative h-5 w-9 shrink-0 rounded-full transition-colors"
              style={{ backgroundColor: plugin.enabled ? 'var(--accent)' : 'var(--rule-strong)' }}
            >
              <span
                aria-hidden="true"
                className="absolute top-0.5 h-4 w-4 rounded-full bg-paper transition-transform"
                style={{ transform: plugin.enabled ? 'translateX(18px)' : 'translateX(2px)' }}
              />
            </button>
          </div>
        ))}
      </div>

      <p className="mt-3 text-[10px] leading-5 text-ink-3">
        禁用的插件不会被意图识别调度。
      </p>
    </div>
  )
}
