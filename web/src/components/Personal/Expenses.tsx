import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { type CurrencyTotals, type ExpenseAssignment, type ExpenseLine, type ExpenseReport, type PlanMeta, newOperationKey, personalApi } from '../../api/personal'
import { formatMoney } from '../../utils/money'
import { originalAmount } from '../../utils/expenseEvidence'
import { Section } from './ui'
import { button, dayTime, input, label, pane, primary, tripHref } from './style'
import { usePersonalResource } from './usePersonalResource'

const localDay = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', dateStyle: 'short' }).format(new Date())
const totals = (currencies: CurrencyTotals) => Object.entries(currencies)
  .map(([code, value]) => originalAmount(value, code)).join(' · ')

export function MonthSpend({ today }: { today: string }) {
  const loader = useCallback((signal: AbortSignal) => personalApi.expenseReport(new URLSearchParams({
    start_date: today.slice(0, 7) + '-01', end_date: today, limit: '1',
  }), signal), [today])
  const { data, error, loading } = usePersonalResource(loader)
  return <Section title="本月实际支出" action={<a href="#/personal/expenses" className={button}>查看账本</a>}>
    {loading ? <p role="status" className="text-sm text-ink-3">正在读取账本…</p> : error
      ? <p role="alert" className="text-sm text-err">账本暂不可用，不代表没有支出。</p>
      : data?.count ? <p className="text-sm font-semibold tabular-nums text-ink">{totals(data.totals_by_currency)}</p>
      : <p className="text-sm text-ink-3">暂无有日期的本月记录。</p>}
  </Section>
}

export function TripSpend({ planId }: { planId: string }) {
  const [view, setView] = useState<ExpenseReport | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    const query = new URLSearchParams({ plan_id: planId, limit: '1' })
    personalApi.expenseReport(query, controller.signal).then(setView)
      .catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [planId])
  return <Section title="实际支出" action={<a href={`#/personal/expenses?trip=${planId}`} className={button}>查看或关联费用</a>}>
    {failed ? <p className="text-sm text-err" role="alert">账本暂时无法读取，不代表没有支出。</p>
      : view ? <p className="text-sm text-ink">{view.count ? totals(view.totals_by_currency) : '暂无有效的已关联费用。'}
        {view.invalid_count > 0 && <span className="ml-2 text-warn">有 {view.invalid_count} 笔异常记录未计入。</span>}</p>
      : <p className="text-sm text-ink-3" role="status">正在读取原账本…</p>}
    <p className="mt-1 text-xs leading-5 text-ink-3">这里只显示原账本中的记录，不会计入行程预算、估算或供应商报价。</p>
  </Section>
}

function GroupedTotals({ data }: { data: Record<string, CurrencyTotals> }) {
  const entries = Object.entries(data).reverse()
  if (!entries.length) return <p className="text-sm text-ink-3">此范围还没有可统计的记录。</p>
  return <dl className="divide-y divide-rule">
    {entries.map(([name, value]) => <div key={name} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
      <dt className="text-ink-2">{name}</dt><dd className="font-semibold text-ink tabular-nums">{totals(value)}</dd>
    </div>)}
  </dl>
}

function LedgerPlot({ data, chronological = false }: { data: Record<string, CurrencyTotals>; chronological?: boolean }) {
  const [table, setTable] = useState(false)
  const [selected, setSelected] = useState('')
  const entries = Object.entries(data)
  const codes = [...new Set(entries.flatMap(([, row]) => Object.keys(row)))].sort()
  const currency = codes.includes(selected) ? selected : codes[0]
  if (!currency) return <GroupedTotals data={data} />
  const rows = entries.flatMap(([name, row]) => {
    const value = row[currency]
    return typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value))
      ? [{ name, value }] : []
  })
  if (chronological) rows.sort((a, b) => a.name.localeCompare(b.name))
  const negative = Math.min(0, ...rows.map(row => Number(row.value)))
  const positive = Math.max(0, ...rows.map(row => Number(row.value)))
  const span = positive - negative || 1
  const scale = (value: number) => 4 + 192 * ((value - negative) / span)
  const zero = scale(0)
  return <div className="min-w-0">
    <div className="mb-2 flex flex-wrap items-end gap-2">
      <label className={label}>图表币种<select className={input} value={currency} onChange={e => setSelected(e.target.value)}>
        {codes.map(code => <option key={code}>{code}</option>)}
      </select></label>
      <button type="button" className={button} aria-pressed={table} onClick={() => setTable(!table)}>{table ? '查看图表' : '查看数据表'}</button>
    </div>
    <p className="mb-2 text-xs text-ink-3">仅比较 {currency}；退款在零线左侧。无数据时不补零。</p>
    {table ? <table className="w-full border-collapse text-left text-sm">
      <caption className="sr-only">{currency} 原币统计数据</caption>
      <thead><tr><th scope="col" className="border-b border-rule py-2">分组</th><th scope="col" className="border-b border-rule py-2 text-right">原币金额</th></tr></thead>
      <tbody>{rows.map(({ name, value }) => <tr key={name}><th scope="row" className="border-b border-rule py-2 font-medium">{name}</th>
        <td className="border-b border-rule py-2 text-right tabular-nums">{originalAmount(value, currency)}</td></tr>)}</tbody>
    </table> : <ul className="divide-y divide-rule">{rows.map(({ name, value }) => {
      const endpoint = scale(Number(value))
      return <li key={name} className="py-2">
        <div className="flex flex-wrap justify-between gap-1 text-sm"><span>{name}</span><b>{originalAmount(value, currency)}</b></div>
        <svg viewBox="0 0 200 16" preserveAspectRatio="none" width="100%" height="16" aria-hidden="true">
          <rect x="4" y="5" width="192" height="6" fill="var(--paper-sunken)" />
          <rect x={Math.min(zero, endpoint)} y="5" width={Math.abs(zero - endpoint)} height="6" fill={Number(value) < 0 ? 'var(--warn)' : 'var(--route)'} />
          <line x1={zero} x2={zero} y1="2" y2="14" stroke="var(--rule-strong)" />
        </svg>
      </li>
    })}</ul>}
  </div>
}

function Assignment({ item, plans, initial, onClose, onDone }: {
  item: ExpenseLine; plans: PlanMeta[]; initial?: string; onClose: () => void; onDone: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const title = useId()
  const fieldId = useId()
  const [target, setTarget] = useState(initial && initial !== item.trip_plan_id ? initial : item.trip_plan_id || '')
  const [preview, setPreview] = useState<ExpenseAssignment | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [stale, setStale] = useState(false)
  const locked = useRef(false)
  const key = useRef('')
  const close = () => { if (!locked.current) onClose() }

  useEffect(() => {
    const node = dialog.current
    node?.showModal()
    return () => node?.close()
  }, [])

  async function act() {
    if (locked.current) return
    locked.current = true; setBusy(true); setError('')
    try {
      if (preview) {
        await personalApi.expenseCommit(item, preview.operation_id, key.current)
        window.dispatchEvent(new Event('expense-updated'))
        onDone()
      } else {
        setPreview(await personalApi.expensePreview(item, target || null))
        key.current = newOperationKey()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '费用归属未保存。')
      if (err && typeof err === 'object' && 'status' in err && [409,410,412].includes(Number(err.status))) setStale(true)
    } finally { setBusy(false); locked.current = false }
  }

  return <dialog ref={dialog} aria-labelledby={title} onCancel={(event) => { event.preventDefault(); close() }}
    className="trip-header m-auto max-h-[85dvh] w-[min(94vw,36rem)] overflow-auto rounded-input border border-rule bg-paper-raised p-4 text-ink shadow-lg backdrop:bg-black/40 sm:p-6">
    <h2 id={title} className="font-display text-2xl font-semibold">调整费用归属</h2>
    <p className="mt-2 break-words text-sm text-ink-2">「{item.description || item.category}」{formatMoney(Number(item.amount), item.currency)}。只更新归属，不修改金额。</p>
    {preview ? <div className="mt-4 text-sm leading-6">
      <p className="trip-calendar-status">预览不会改动账本。确认后只更新归属。</p>
      <div className="trip-change-board">
        <section aria-label="原归属"><h3>原归属</h3>{preview.before_title || '未归属'}</section>
        <section data-proposed aria-label="拟归属"><h3>拟归属</h3>{preview.after_title || '未归属'}</section>
      </div>
      <p className="text-xs text-ink-3">有效至 {dayTime(preview.expires_at)}（北京时间）</p>
    </div> : <div className={`${label} mt-4`}>
      <label htmlFor={fieldId}>费用归属</label>
      <select id={fieldId} className={input} value={target} disabled={busy} onChange={(event) => { setTarget(event.target.value); setError(''); setStale(false) }}>
        <option value="">未归属</option>
        {plans.map((plan) => <option key={plan.plan_id} value={plan.plan_id}>{plan.title}</option>)}
        {item.trip_plan_id && !plans.some((plan) => plan.plan_id === item.trip_plan_id) &&
          <option value={item.trip_plan_id}>当前归属（未在列表中）</option>}
      </select>
    </div>}
    {error && <p role="alert" className="mt-2 text-sm text-err">{error}</p>}
    <div className="mt-4 flex flex-wrap justify-end gap-2">
      <button type="button" className={button} onClick={close} disabled={busy}>取消</button>
      {stale ? <button type="button" className={button} onClick={onDone}>重新读取费用</button>
        : <button type="button" className={primary} disabled={busy || (!preview && (target || null) === item.trip_plan_id)}
          onClick={() => { void act() }}>{busy ? '正在处理…' : preview ? '确认更新归属' : '预览归属变更'}</button>}
    </div>
  </dialog>
}

export default function Expenses({ trip }: { trip?: string }) {
  const [scope, setScope] = useState(trip || '')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [offset, setOffset] = useState(0)
  const [plans, setPlans] = useState<PlanMeta[]>([])
  const [plansError, setPlansError] = useState(false)
  const [trend, setTrend] = useState<'month' | 'year'>('month')
  const [active, setActive] = useState<ExpenseLine | null>(null)
  const related = trip && plans.find((plan) => plan.plan_id === trip)

  const loader = useCallback((signal: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: '20' })
    if (scope === 'unassigned') params.set('unassigned', 'true')
    else if (scope) params.set('plan_id', scope)
    if (start) params.set('start_date', start)
    if (end) params.set('end_date', end)
    return personalApi.expenseReport(params, signal)
  }, [scope, start, end, offset])
  const { data: report, error, loading, retry } = usePersonalResource(loader)

  useEffect(() => {
    const controller = new AbortController()
    personalApi.list(new URLSearchParams({ limit: '60' }), controller.signal)
      .then(({ items }) => setPlans(items)).catch(() => { if (!controller.signal.aborted) setPlansError(true) })
    window.addEventListener('expense-updated', retry)
    return () => { controller.abort(); window.removeEventListener('expense-updated', retry) }
  }, [retry])

  function period(kind: 'all' | 'month' | 'year') {
    const now = localDay()
    setStart(kind === 'all' ? '' : kind === 'month' ? now.slice(0, 7) + '-01' : now.slice(0, 4) + '-01-01')
    setEnd(kind === 'all' ? '' : now)
    setOffset(0)
  }

  return <div className="space-y-4">
    <div className={pane}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm text-ink-2">{related ? `从「${related.title}」打开此账本视图。` : '这里只汇总已记录的实际支出，按原币种分别计算。'}</p>
        <button type="button" className={button} onClick={() => period('all')}>全部日期</button>
        <button type="button" className={button} onClick={() => period('month')}>本月</button>
        <button type="button" className={button} onClick={() => period('year')}>本年</button>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className={label}>关联范围<select className={input} value={scope} onChange={(e) => { setScope(e.target.value); setOffset(0) }}>
          <option value="">所有费用</option><option value="unassigned">未归属费用</option>
          {plans.map((plan) => <option key={plan.plan_id} value={plan.plan_id}>{plan.title}</option>)}
          {trip && !related && <option value={trip}>链接所指行程</option>}
        </select></label>
        <label className={label}>发生日期起<input type="date" className={input} value={start} onChange={(e) => { setStart(e.target.value); setOffset(0) }} /></label>
        <label className={label}>发生日期止<input type="date" className={input} min={start || undefined} value={end} onChange={(e) => { setEnd(e.target.value); setOffset(0) }} /></label>
      </div>
    </div>
    {loading && <p role="status" className="p-4 text-sm text-ink-3">正在读取账本…</p>}
    {plansError && <p role="alert" className="text-sm text-warn">行程清单暂不可用，账本汇总不受影响。</p>}
    {error && <div className={pane}><p role="alert" className="text-sm text-err">{error}</p>
      <button type="button" className={`${button} mt-2`} onClick={retry}>重试</button></div>}
    {report && <>
      <Section className="trip-header" title="实际支出（原币种）">
        <p className="text-lg font-semibold tabular-nums">{report.count ? totals(report.totals_by_currency) : '暂无费用记录'}</p>
        <p className="mt-1 text-sm text-ink-3">本范围 {report.count} 笔，包含退款，不做混币换算。</p>
        {report.invalid_count > 0 && <p role="status" className="text-sm text-warn">{report.invalid_count} 笔旧记录无有效金额或币种，未计入。</p>}
        {report.unknown_date_count > 0 && <p className="text-sm text-ink-3">{report.unknown_date_count} 笔无发生日期，不计入月年趋势。</p>}
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="分类统计"><LedgerPlot data={report.by_category} /></Section>
        <Section title="费用趋势" action={<label className="flex items-center gap-2 text-sm text-ink-2">
          显示<select className={input} value={trend} onChange={(e) => setTrend(e.target.value as 'month' | 'year')}>
            <option value="month">按月</option><option value="year">按年</option>
          </select></label>}><LedgerPlot data={trend === 'month' ? report.by_month : report.by_year} chronological /></Section>
      </div>
      <Section title="费用明细" action={<a className={button} href="#/">返回对话记账</a>}>
        {!report.items.length && <p className="py-2 text-sm text-ink-3">没有符合条件的记录。</p>}
        <ul className="divide-y divide-rule">{report.items.map((row) => {
          const linked = plans.find((plan) => row.trip_plan_id === plan.plan_id)
          return <li key={row.entry_ref} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
            <div className="min-w-0 flex-1 basis-32 break-words">
              <p className="text-sm font-semibold">{row.description || row.category}</p>
              <p className="text-xs text-ink-3">{row.category} · {row.date || '日期未知'} ·{' '}
                {row.trip_plan_id ? <a className="text-accent underline" href={tripHref(row.trip_plan_id)}>{linked?.title || '已关联'}</a> : '未归属'}</p>
            </div>
            <strong className="text-sm tabular-nums">{originalAmount(row.amount, row.currency)}</strong>
            <button type="button" className={button} onClick={() => setActive(row)}>调整归属</button>
          </li>
        })}</ul>
        {offset > 0 && <button type="button" className={button} onClick={() => setOffset(Math.max(0, offset - 20))}>上一页</button>}
        {report.next_offset != null && <button type="button" className={button} onClick={() => setOffset(report.next_offset ?? 0)}>下一页</button>}
      </Section>
    </>}
    {active && <Assignment item={active} plans={plans.filter((plan) => ['draft','scheduled','completed'].includes(plan.lifecycle))}
      initial={trip} onClose={() => setActive(null)} onDone={() => { setActive(null); retry() }} />}
  </div>
}
