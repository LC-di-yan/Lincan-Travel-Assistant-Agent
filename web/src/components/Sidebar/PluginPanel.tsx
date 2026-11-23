import { useState, useEffect, useRef } from 'react'

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
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState('')
  const [pending, setPending] = useState('')
  const lock = useRef(false)

  useEffect(() => {
    const request = new AbortController()
    fetch('/api/plugins', { signal: request.signal })
      .then((r) => { if (!r.ok) throw new Error(); return r.json() })
      .then((d) => {
        if (!Array.isArray(d.plugins)) throw new Error()
        if (!request.signal.aborted) setPlugins(d.plugins)
      })
      .catch(() => { if (!request.signal.aborted) setError('暂时无法读取插件状态。') })
      .finally(() => { if (!request.signal.aborted) setLoading(false) })
    return () => request.abort()
  }, [attempt])

  const toggle = async (name: string, enabled: boolean) => {
    if (lock.current) return
    lock.current = true
    setPending(name)
    setError('')
    try {
      const res = await fetch('/api/plugins', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, enabled }),
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      if (!Array.isArray(data.plugins)) throw new Error()
      setPlugins(data.plugins)
    } catch {
      setError('未收到插件更新回执。保持上次已知状态，请重试或重新读取。')
    } finally {
      lock.current = false
      setPending('')
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
      {error && <div className="my-2 border border-rule p-2 text-xs text-err">
        <p role="alert">{error}</p>
        <button type="button" className="min-h-11 font-semibold text-route underline" disabled={!!pending}
          onClick={() => { setLoading(true); setError(''); setAttempt(n => n + 1) }}>重新读取插件状态</button>
      </div>}

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
              disabled={!!pending}
              aria-label={(plugin.enabled ? '禁用 ' : '启用 ') + (friendlyNames[plugin.name] || plugin.name)}
              onClick={() => toggle(plugin.name, !plugin.enabled)}
              className="grid size-11 shrink-0 place-items-center rounded-input disabled:opacity-55"
            >
              <span aria-hidden="true" className="relative h-5 w-9 rounded-full" style={{ backgroundColor: plugin.enabled ? 'var(--route)' : 'var(--rule-strong)' }}>
              <span
                aria-hidden="true"
                className="absolute top-0.5 h-4 w-4 rounded-full bg-paper transition-transform"
                style={{ transform: plugin.enabled ? 'translateX(18px)' : 'translateX(2px)' }}
              />
              </span>
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
