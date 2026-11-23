import { useEffect, useRef, useState } from 'react'
import { type PreferenceItem, type PreferencesView, personalApi } from '../../api/personal'
import { Section } from './ui'
import { button, input, label, pane, primary } from './style'

function valueOf(item: PreferenceItem) {
  if (Array.isArray(item.value)) return item.value.join('、')
  if (typeof item.value === 'object' && item.value) return item.value.amount
  return item.value || ''
}

function FieldEditor({ item, disabled, enabled, updated, onSave }: {
  item: PreferenceItem; disabled: boolean; enabled: boolean; updated: boolean
  onSave: (value: string | { amount: string; currency: string } | null, use: boolean) => void
}) {
  const saved = valueOf(item)
  const [value, setValue] = useState(saved)
  const [currency, setCurrency] = useState(item.value && !Array.isArray(item.value) && typeof item.value === 'object' ? item.value.currency : 'CNY')
  const [use, setUse] = useState(item.use_for_planning)
  const money = item.key === 'nightly_budget'
  const state = !saved ? '尚未设置' : item.supported_for_planning && item.use_for_planning && enabled ? '允许用于规划' : '仅保存'
  const field = item.key === 'departure_period'
    ? <select className={input} value={value} onChange={(e) => setValue(e.target.value)}><option value="">未设置</option>
        {['上午', '下午', '晚上'].map((x) => <option key={x}>{x}</option>)}</select>
    : <input className={input} type={money ? 'number' : 'text'} min={money ? 0 : undefined} step={money ? '0.01' : undefined} maxLength={120}
        placeholder={item.key === 'home_city' ? '例如：上海（仅城市）' : undefined}
        value={value} onChange={(e) => setValue(e.target.value)} />
  return <form className="grid min-w-0 gap-2 border-b border-rule py-3 last:border-none lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto] lg:items-end"
    onSubmit={(event) => { event.preventDefault(); onSave(value.trim() ? (money ? { amount: value, currency } : value.trim()) : null, Boolean(value.trim() && use)) }}>
    <p className="text-xs text-ink-3 lg:col-span-3"><b className="text-route">{state}</b>
      {item.use_for_planning && !enabled ? ' · 总开关已停用，授权设置仍保留。' : state === '仅保存' ? ' · 不用于生成或排序方案。' : ''}
      {updated && <span className="ml-2 text-ok">本项已更新</span>}</p>
    <div className="flex min-w-0 items-end gap-2">
      <label className={`${label} flex-1`}>{item.label}{field}</label>
      {money && <label className={label}>币种<select className={input} value={currency} onChange={(e) => setCurrency(e.target.value)}>
        {Array.from(new Set(['CNY','USD','EUR','HKD','JPY', currency])).map((code) => <option key={code}>{code}</option>)}
      </select></label>}
    </div>
    {item.supported_for_planning
      ? <label className="flex min-h-11 items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" className="h-4 w-4" disabled={!value.trim()} checked={use} onChange={(event) => setUse(event.target.checked)} />
          允许用于规划
        </label>
      : <span className="self-center text-sm text-ink-3">目前仅保存，不参与排序</span>}
    <div className="flex flex-wrap gap-2">
      <button type="submit" className={button} disabled={disabled}>保存{item.label}</button>
      {saved && <button type="button" className={button} disabled={disabled} onClick={() => onSave(null, false)}>清除</button>}
    </div>
  </form>
}

export default function Preferences() {
  const [view, setView] = useState<PreferencesView | null>(null)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [updated, setUpdated] = useState('')
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const [attempt, retry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    personalApi.preferences(controller.signal).then(setView).catch((err) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : '偏好暂不可读。')
    })
    return () => controller.abort()
  }, [attempt])

  async function apply(command: () => Promise<PreferencesView>, field = '') {
    if (locked.current) return
    locked.current = true
    setBusy(true); setError(''); setStatus('')
    try {
      setView(await command())
      setStatus('偏好设置已更新。')
      setUpdated(field)
      window.dispatchEvent(new Event('preference-updated'))
    } catch (err) { setError(err instanceof Error ? err.message : '偏好未更新。') }
    finally { locked.current = false; setBusy(false) }
  }

  return <div className="space-y-4">
    <div className={`${pane} trip-header`}>
      <p className="trip-kicker mb-1">ALIGO / 授权档案</p>
      <h2 className="font-display text-xl font-semibold">个性化规划</h2>
      <p className="mt-2 text-sm leading-6 text-ink-2">只有你授权的项目才会用于规划。单次的日期、预算或交通要求不会改写长期偏好；这次明确提出的约束优先。</p>
      {view && <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <span>当前：{view.enabled ? '已启用' : '未启用'}</span>
        <button className={primary} type="button" disabled={busy} onClick={() => { void apply(() => personalApi.setting(!view.enabled, view.revision)) }}>
          {view.enabled ? '停用个性化规划' : '启用已授权的偏好'}
        </button>
      </div>}
      <p className="mt-2 text-xs text-ink-3">停用后仍保留你保存的设置。常用城市只能作为确认提示，助手不会擅自选为起点。</p>
    </div>
    {status && <p role="status" className="text-sm text-ok">{status}</p>}
    {error && <div className={pane}><p role="alert" className="text-sm text-err">{error}</p>
      <button type="button" className={`${button} mt-2`} onClick={() => { setError(''); retry((n) => n + 1) }}>重新读取</button></div>}
    {view ? <Section title="我的偏好">
      {view.items.map((item) => <FieldEditor key={JSON.stringify(item)} item={item} disabled={busy} enabled={view.enabled} updated={updated === item.key}
        onSave={(value, use) => { void apply(() => personalApi.editPreference(item.key, value, use, view.revision), item.key) }} />)}
    </Section> : !error && <p role="status" className="text-sm text-ink-3">正在读取我的偏好…</p>}
  </div>
}
