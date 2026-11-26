import { type FormEvent, useLayoutEffect, useRef, useState } from 'react'
import type { DraftContent, PlanEvent } from '../../api/personal'
import { button, days, input, label, pane, primary } from './style'
import { originalAmount } from '../../utils/expenseEvidence'

const categories: Record<PlanEvent['kind'], string> = {
  rail: '铁路', flight: '飞机', meeting: '会议', check_in: '入住', check_out: '退房', activity: '活动', buffer: '预留时间',
}

function displayLocal(value?: string | null) {
  if (!value) return ''
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', hourCycle: 'h23', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
  return parts.replace(' ', 'T')
}

function localIso(value: string) {
  return value ? `${value}:00+08:00` : null
}

const newEvent = (): PlanEvent => ({ title: '', kind: 'meeting', commitment: 'fixed', precision: 'exact', timezone: 'Asia/Shanghai' })

interface Entry { key: number; event: PlanEvent }

export default function TripForm({ initial, onSave, cancel, preserveEvents = false }: {
  initial?: DraftContent
  onSave: (draft: DraftContent) => Promise<unknown>
  cancel: string
  preserveEvents?: boolean
}) {
  const [draft, setDraft] = useState<DraftContent>(() => initial || { title: '' })
  const [entries, setEntries] = useState<Entry[]>(() => (initial?.schedule_items || []).map((event, key) => ({ event, key })))
  const next = useRef(entries.length)
  const addActivity = useRef<HTMLButtonElement>(null)
  const removeControls = useRef(new Map<number, HTMLButtonElement>())
  const activityFocus = useRef<{ key?: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const [error, setError] = useState('')
  const [amount, setAmount] = useState(initial?.budget?.amount || '')
  const [currency, setCurrency] = useState(initial?.budget?.currency || 'CNY')
  const edit = (key: number, changes: Partial<PlanEvent>) => setEntries((old) => old.map((row) => row.key === key ? { ...row, event: { ...row.event, ...changes } } : row))
  const field = (name: keyof DraftContent, value: string) => setDraft((old) => ({ ...old, [name]: value }))

  useLayoutEffect(() => {
    const target = activityFocus.current
    if (!target) return
    activityFocus.current = null
    const button = target.key === undefined ? addActivity.current : removeControls.current.get(target.key)
    button?.focus()
  }, [entries])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setError('')
    try {
      await onSave({
        title: draft.title.trim(), origin: draft.origin?.trim() || null, destination: draft.destination?.trim() || null,
        start_date: draft.start_date || null, end_date: draft.end_date || null, notes: draft.notes?.trim() || '',
        budget: amount ? { amount, currency } : null,
        schedule_items: entries.map(({ event }) => ({
          ...event, city: event.city?.trim() || null, arrival_city: event.arrival_city?.trim() || null,
          place: event.place?.trim() || null, arrival_place: event.arrival_place?.trim() || null,
          start_at: event.precision === 'exact' || event.precision === 'window' ? event.start_at : null,
          end_at: event.precision === 'exact' || event.precision === 'window' ? event.end_at : null,
          local_date: event.precision === 'date_only' ? event.local_date || null : null,
          end_date: event.precision === 'date_only' ? event.end_date || null : null,
        })),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '未能保存，请重试。')
    } finally {
      setBusy(false)
      locked.current = false
    }
  }

  return <form onSubmit={(event) => { void submit(event) }} className="trip-form-layout">
    <aside className={`${pane} trip-header trip-form-preview`} aria-label="草稿简报">
      <p className="trip-kicker">ALIGO / 草稿简报</p>
      <h2 className="mt-1 break-words font-display text-xl font-semibold">{draft.title.trim() || '未命名行程'}</h2>
      <p className="mt-2 break-words text-sm text-ink-2">{draft.origin || '起点待定'} → {draft.destination || '终点待定'}</p>
      <p className="text-sm text-ink-3">{days(draft.start_date, draft.end_date)} · {entries.length} 项活动</p>
      <p className="mt-2 text-sm text-ink-2">计划预算：{amount ? originalAmount(amount, currency) : '未填写'}</p>
      <p className="mt-2 text-xs text-ink-3">保存只生成草稿，不加入安排。</p>
    </aside>
    <div className={`${pane} space-y-5`}>
    {preserveEvents && <p className="rounded-input border border-rule bg-paper-sunken p-3 text-sm leading-6 text-ink-2">
      手动编辑会生成新草稿。保留已有活动，但不会继承旧报价的核验状态，也不改变已安排版本。
    </p>}
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="mb-3 font-display text-xl font-semibold">路线与日期</legend>
      <label className={`${label} sm:col-span-2`}>行程名称<input className={input} value={draft.title} required maxLength={120} onChange={(e) => field('title', e.target.value)} /></label>
      <label className={label}>出发城市<input className={input} value={draft.origin ?? ''} minLength={2} maxLength={32} onChange={(e) => field('origin', e.target.value)} /></label>
      <label className={label}>目的城市<input className={input} value={draft.destination ?? ''} minLength={2} maxLength={32} onChange={(e) => field('destination', e.target.value)} /></label>
      <label className={label}>出发日期<input type="date" className={input} value={draft.start_date ?? ''} onChange={(e) => field('start_date', e.target.value)} /></label>
      <label className={label}>结束日期<input type="date" className={input} value={draft.end_date ?? ''} min={draft.start_date || undefined} onChange={(e) => field('end_date', e.target.value)} /></label>
      <label className={`${label} sm:col-span-2`}>备注<textarea className={`${input} py-2`} rows={2} value={draft.notes ?? ''} maxLength={600} onChange={(e) => field('notes', e.target.value)} /></label>
    </fieldset>
    <div className="border-t border-rule pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-xl font-semibold">行程活动</h2>
        <button ref={addActivity} type="button" className={button} disabled={entries.length >= 120} onClick={() => setEntries([...entries, { key: next.current++, event: newEvent() }])}>添加活动</button>
      </div>
      <p className="mt-1 text-sm text-ink-3">时间按北京时间填写。不能确定具体时段时，可只填写日期。</p>
      {entries.map(({ key, event }, index) => <fieldset key={key} className="mt-3 grid gap-3 rounded-input border border-rule p-3 sm:grid-cols-2">
        <legend className="px-1 text-sm font-semibold">活动 {index + 1}</legend>
        <label className={label}>活动名称<input required maxLength={120} className={input} value={event.title} onChange={(e) => edit(key, { title: e.target.value })} /></label>
        <label className={label}>类型<select className={input} value={event.kind} onChange={(e) => {
          const desired = e.target.value as PlanEvent['kind']
          edit(key, { kind: desired, before_minutes: desired === 'rail' ? 60 : 0 })
        }}>
          {Object.entries(categories).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select></label>
        <label className={label}>城市<input className={input} value={event.city ?? ''} minLength={2} maxLength={32} onChange={(e) => edit(key, { city: e.target.value })} /></label>
        <label className={label}>地点或车站<input className={input} value={event.place ?? ''} maxLength={120} onChange={(e) => edit(key, { place: e.target.value })} /></label>
        {(event.kind === 'rail' || event.kind === 'flight') && <>
          <label className={label}>抵达城市<input className={input} value={event.arrival_city ?? ''} minLength={2} maxLength={32} onChange={(e) => edit(key, { arrival_city: e.target.value })} /></label>
          <label className={label}>抵达站点<input className={input} value={event.arrival_place ?? ''} maxLength={120} onChange={(e) => edit(key, { arrival_place: e.target.value })} /></label>
        </>}
        <label className={label}>时间精度<select className={input} value={event.precision} onChange={(e) => edit(key, { precision: e.target.value as PlanEvent['precision'] })}>
          <option value="exact">确定时段</option><option value="window">大致时间窗</option><option value="date_only">仅日期</option><option value="unknown">待定</option>
        </select></label>
        <label className={label}>占用方式<select className={input} value={event.commitment} onChange={(e) => edit(key, { commitment: e.target.value as PlanEvent['commitment'] })}>
          <option value="fixed">必须参加或执行</option><option value="soft">可灵活调整</option>
        </select></label>
        {(event.precision === 'exact' || event.precision === 'window') && <>
          <label className={label}>开始时间<input required type="datetime-local" className={input} value={displayLocal(event.start_at)} onChange={(e) => edit(key, { start_at: localIso(e.target.value) })} /></label>
          <label className={label}>结束时间<input required type="datetime-local" className={input} value={displayLocal(event.end_at)} onChange={(e) => edit(key, { end_at: localIso(e.target.value) })} /></label>
          <label className={label}>提前预留（分钟）<input type="number" min="0" max="720" className={input} value={event.before_minutes ?? 0}
            onChange={(e) => edit(key, { before_minutes: Number(e.target.value) })} /></label>
          <label className={label}>结束后预留（分钟）<input type="number" min="0" max="720" className={input} value={event.after_minutes ?? 0}
            onChange={(e) => edit(key, { after_minutes: Number(e.target.value) })} /></label>
        </>}
        {event.precision === 'date_only' && <>
          <label className={label}>开始日期<input required type="date" className={input} value={event.local_date ?? ''} onChange={(e) => edit(key, { local_date: e.target.value })} /></label>
          <label className={label}>结束日期（可选）<input type="date" className={input} value={event.end_date ?? ''} min={event.local_date || undefined} onChange={(e) => edit(key, { end_date: e.target.value })} /></label>
        </>}
        <button type="button" className={`${button} justify-self-start text-err`}
          ref={node => { if (node) removeControls.current.set(key, node); else removeControls.current.delete(key) }}
          onClick={event => {
            if (event.detail === 0) activityFocus.current = { key: (entries[index + 1] ?? entries[index - 1])?.key }
            setEntries(entries.filter((row) => row.key !== key))
          }}>移除活动 {index + 1}</button>
      </fieldset>)}
    </div>
    <fieldset className="grid gap-3 border-t border-rule pt-3 sm:grid-cols-2">
      <legend className="mb-2 font-display text-xl font-semibold">计划预算</legend>
      <label className={label}>预算金额<input type="number" step="0.01" min="0" className={input} value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
      <label className={label}>预算币种<select className={input} value={currency} onChange={(e) => setCurrency(e.target.value)}>
        {Array.from(new Set(['CNY','USD','EUR','JPY','HKD', currency])).map((code) => <option key={code}>{code}</option>)}
      </select></label>
    </fieldset>
    {error && <p role="alert" className="text-sm leading-6 text-err">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <button type="submit" className={primary} disabled={busy}>{busy ? '正在保存…' : initial ? '保存为新版本' : '创建草稿'}</button>
      <a href={cancel} className={button}>取消</a>
    </div>
    </div>
  </form>
}
