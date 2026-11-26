import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type RefObject } from 'react'
import { ArrowLeft, ArrowUpRight, Bookmark, CalendarDays, FileText, Plus, SlidersHorizontal, Wallet } from 'lucide-react'
import { type ActionReceipt, type CreateContent, type DraftContent, type Lifecycle, type PlanMeta, type PlanVersion, type ScheduleAction, type TripDetail, type VersionInfo, newOperationKey, personalApi } from '../../api/personal'
import { useChatStore } from '../../store/chatStore'
import { formatMoney } from '../../utils/money'
import TripForm from './TripForm'
import { PlanList, Section, StableResourceRegion } from './ui'
import { button, dayTime, days, input, lifecycleLabel, pane, primary, tripHref } from './style'
import { usePersonalResource as useLoad } from './usePersonalResource'
import CalendarOperation from './CalendarOperation'
import { calendarText, downloadCalendar } from './calendar'
import Expenses, { MonthSpend, TripSpend } from './Expenses'
import Favorites, { FavoriteButton } from './Favorites'
import Preferences from './Preferences'
import { EventRows, VersionBoard } from './TripRhythm'
import { versionEvents } from './tripTimeline'

function RequestState({ loading, error, retry }: { loading: boolean; error: string; retry: () => void }) {
  if (loading) return <p role="status" className="py-5 text-sm text-ink-3">正在读取行程资料…</p>
  if (!error) return null
  return <div className={`${pane} flex flex-wrap items-center justify-between gap-3`}>
    <p role="alert" className="text-sm text-err">{error}</p><button type="button" className={button} onClick={retry}>重试</button>
  </div>
}

function useIdempotent<T extends object>(save: (data: T, key: string) => Promise<ActionReceipt>) {
  const last = useRef<{ encoded: string; key: string } | null>(null)
  return (payload: T) => {
    const encoded = JSON.stringify(payload)
    if (last.current?.encoded !== encoded) last.current = { encoded, key: newOperationKey() }
    return save(payload, last.current.key)
  }
}

function useRouteContinuation(routeKey?: string) {
  const lifetime = useRef<object | null>(null)
  useLayoutEffect(() => {
    lifetime.current = {}
    return () => { lifetime.current = null }
  }, [routeKey])

  return () => {
    const origin = lifetime.current
    const hash = window.location.hash
    // A completed write may outlive its form, but its navigation must not.
    return () => origin !== null && lifetime.current === origin && window.location.hash === hash
  }
}

function NextArrangement({ plan }: { plan: PlanMeta & { scheduled_version: number } }) {
  const loader = useCallback((signal: AbortSignal) => personalApi.version(plan.plan_id, plan.scheduled_version, signal), [plan.plan_id, plan.scheduled_version])
  const { data, error } = useLoad(loader)
  const route = [data?.snapshot.origin, data?.snapshot.destination].filter(Boolean).join(' → ')
  return <>
    <PlanList rows={[plan]} empty="" agenda />
    {route ? <p className="px-2 py-1 text-sm text-route">已安排路线：{route}</p>
      : error && <p className="px-2 text-xs text-ink-3">未能读取已安排路线，请打开版本核对。</p>}
  </>
}

function OverviewPage() {
  const loader = useCallback((signal: AbortSignal) => personalApi.overview(signal), [])
  const resource = useLoad(loader)
  if (!resource.data) return <RequestState {...resource} />
  const { today, counts, upcoming, recent_drafts, frequent_destinations } = resource.data
  const [next, ...later] = upcoming.filter((row): row is PlanMeta & { scheduled_version: number } =>
    row.lifecycle === 'scheduled' && row.scheduled_version != null)
  if (!counts.scheduled && !counts.draft && !recent_drafts.length && !frequent_destinations.length) return <>
    <Section className="trip-header" title="从一份草稿开始"
      action={<a href="#/personal/trips/new" className={primary}><Plus size={17} aria-hidden="true" />新建草稿</a>}>
      <p className="text-sm text-ink-2">草稿可以随时调整，不占用日历。只有你明确确认的版本才会出现在安排里。</p>
    </Section>
    <div className="mt-4"><MonthSpend today={today} /></div>
  </>
  return <>
    <div className="mb-5 flex flex-wrap items-center justify-between gap-2 text-sm text-ink-2">
      <p>北京时间 · {today}<span className="ml-3 text-ink-3">{counts.scheduled} 项安排 · {counts.draft} 份草稿</span></p>
      <a href="#/personal/trips/new" className={primary}><Plus size={17} aria-hidden="true" />新建草稿</a>
    </div>
    <Section className="trip-header mb-4" title="下一项已安排" action={<a className={button} href="#/personal/trips?view=agenda">查看已安排议程</a>}>
      {next ? <NextArrangement plan={next} /> : <p className="py-3 text-sm text-ink-3">没有即将开始的安排。草稿不会占用日历。</p>}
      {later.length > 0 && <details className="mt-2 border-t border-rule">
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold text-route">后续还有 {later.length} 项已安排</summary>
        <PlanList rows={later} empty="" agenda />
      </details>}
    </Section>
    <div className="grid gap-4 lg:grid-cols-2">
      <Section title="最近保存的草稿"><PlanList rows={recent_drafts} empty="还没有草稿。先在对话中生成一份行程，或手动新建。" /></Section>
      <Section title="常去城市">
        {frequent_destinations.length ? <ul className="space-y-2 text-sm">
          {frequent_destinations.map(({ city, count }) => <li key={city}>{city} · {count} 次已标记完成</li>)}
        </ul> : <p className="text-sm text-ink-3">过去一年暂无本人标记完成的行程。旧摘要不计入。</p>}
      </Section>
      <MonthSpend today={today} />
    </div>
    <p className="mt-5 text-xs leading-6 text-ink-3">目前资料保存在当前浏览器身份下。清除浏览器身份后，系统无法自动找回这些资料。</p>
  </>
}

function TripsPage({ initialAgenda = false }: { initialAgenda?: boolean }) {
  const [status, setStatus] = useState<Lifecycle | ''>(initialAgenda ? 'scheduled' : '')
  const [filtersOpen, setFiltersOpen] = useState(() => matchMedia('(min-width: 650px)').matches)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [cursor, setCursor] = useState('')
  const loader = useCallback((signal: AbortSignal) => {
    const params = new URLSearchParams({ limit: '20' })
    if (status) params.set('status', status)
    if (filter) params.set('search', filter)
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    if (cursor) params.set('cursor', cursor)
    return personalApi.list(params, signal)
  }, [status, filter, cursor, startDate, endDate])
  const resource = useLoad(loader)
  const submit = (event: FormEvent) => { event.preventDefault(); setCursor(''); setFilter(search.trim()) }

  return <>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-ink-2">安排和草稿是独立状态，历史摘要不会计入日历。</p>
      <a href="#/personal/trips/new" className={primary}><Plus size={17} aria-hidden="true" />新建草稿</a>
    </div>
    <div className="mb-3 flex flex-wrap gap-2">
      <button type="button" className={button} aria-pressed={status !== 'scheduled'} onClick={() => { setCursor(''); setStatus('') }}>全部行程</button>
      <button type="button" className={button} aria-pressed={status === 'scheduled'} onClick={() => { setCursor(''); setStatus('scheduled') }}>已安排议程</button>
    </div>
    <details className={`${pane} mb-4`} open={filtersOpen} onToggle={e => setFiltersOpen(e.currentTarget.open)}>
      <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold text-route">
        筛选行程{filter ? ` · ${filter}` : ''}{status ? ` · ${lifecycleLabel[status]}` : ''}{startDate || endDate ? ` · ${startDate || '不限'} 至 ${endDate || '不限'}` : ''}
      </summary>
      <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
      <label className="grid min-w-32 flex-1 gap-1.5 text-sm text-ink-2">名称或城市
        <input className={input} value={search} maxLength={100} onChange={(e) => setSearch(e.target.value)} />
      </label>
      <label className="grid min-w-28 gap-1.5 text-sm text-ink-2">状态
        <select className={input} value={status} onChange={(e) => { setCursor(''); setStatus(e.target.value as Lifecycle | '') }}>
          <option value="">全部活动状态</option>
          {Object.entries(lifecycleLabel).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
        </select>
      </label>
      <label className="grid min-w-28 gap-1.5 text-sm text-ink-2">日期起<input type="date" className={input}
        value={startDate} onChange={(e) => { setCursor(''); setStartDate(e.target.value) }} /></label>
      <label className="grid min-w-28 gap-1.5 text-sm text-ink-2">日期止<input type="date" className={input}
        min={startDate || undefined} value={endDate} onChange={(e) => { setCursor(''); setEndDate(e.target.value) }} /></label>
      <button type="submit" className={button}>搜索</button>
      </form>
    </details>
    <Section className="trip-header" title={status === 'scheduled' ? '已安排议程' : '已保存行程'}>
      <StableResourceRegion holding={resource.loading || !!resource.error}>
      <RequestState {...resource} />
      {status === 'scheduled' && <p className="mb-2 text-xs text-ink-3">按本页已安排日期排列，不根据分页结果判断空闲日期。</p>}
      {resource.data && <PlanList rows={status === 'scheduled'
        ? [...resource.data.items].sort((a, b) => (a.scheduled_start_date || '9999').localeCompare(b.scheduled_start_date || '9999'))
        : resource.data.items} empty="没有符合条件的行程。" agenda={status === 'scheduled'} />}
      <div className="flex flex-wrap gap-2">
        {cursor && <button type="button" className={button} onClick={() => setCursor('')}>返回第一页</button>}
        {resource.data?.next_cursor && <button type="button" className={button}
          onClick={() => setCursor(resource.data?.next_cursor || '')}>下一页</button>}
      </div>
      </StableResourceRegion>
    </Section>
    {status !== 'scheduled' && <LegacyTrips />}
  </>
}

function LegacyTrips() {
  const loader = useCallback((signal: AbortSignal) => personalApi.legacy(signal), [])
  const resource = useLoad(loader)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const copy = useIdempotent((data: CreateContent, key) => personalApi.create(data, key))
  const captureRoute = useRouteContinuation()

  return <div className="mt-4">
    <Section title="旧对话的行程摘要">
      <p className="text-sm leading-6 text-ink-3">这些记录只保留了行程摘要。复制后可补齐细节，不会自动加入日历。</p>
      <RequestState {...resource} />
      {resource.data && (resource.data.items.length ? <ul className="mt-2 divide-y divide-rule">
        {resource.data.items.map((row, index) => <li key={`${row.trip_id}:${index}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
          <span className="text-sm text-ink">{row.origin || '起点待定'} → {row.destination || '终点待定'} · {days(row.start_date, row.end_date)}</span>
          <button type="button" className={button} disabled={!!busy || row.ambiguous} onClick={async () => {
            const stillHere = captureRoute()
            setBusy(row.trip_id)
            setError('')
            try {
              const next = await copy({ source: 'historical_summary', trip_id: row.trip_id })
              if (stillHere()) window.location.hash = tripHref(next.plan_id)
            } catch (err) { setError(err instanceof Error ? err.message : '复制失败。') }
            finally { setBusy('') }
          }}>{row.ambiguous ? '编号重复，请手动新建' : busy === row.trip_id ? '正在复制…' : '复制为草稿'}</button>
        </li>)}
      </ul> : <p className="py-4 text-sm text-ink-3">暂无旧行程摘要。</p>)}
      {error && <p role="alert" className="mt-2 text-sm text-err">{error}</p>}
    </Section>
  </div>
}

function DetailPage({ id, selectedVersion }: { id: string; selectedVersion?: number }) {
  const [receipt, setReceipt] = useState<ActionReceipt | null>(null)
  const previous = useRef({ id, selectedVersion })
  const movingVersion = useRef(false)
  const versionBoard = useRef<HTMLDivElement>(null)
  const requestState = useRef<HTMLDivElement>(null)
  const loader = useCallback(async (signal: AbortSignal) => {
    const [detail, versions] = await Promise.all([personalApi.get(id, signal), personalApi.versions(id, signal)])
    const shown = selectedVersion != null ? await personalApi.version(id, selectedVersion, signal) : detail.draft
    return { detail, items: versions.items, shown }
  }, [id, selectedVersion])
  const resource = useLoad(loader)
  useLayoutEffect(() => {
    if (previous.current.id !== id) movingVersion.current = false
    else if (previous.current.selectedVersion !== selectedVersion) movingVersion.current = true
    previous.current = { id, selectedVersion }
    if (!movingVersion.current) return
    const available = document.activeElement === document.body || document.activeElement === requestState.current
    if (resource.loading) {
      if (available) requestState.current?.focus({ preventScroll: true })
    } else {
      if (!resource.error) movingVersion.current = false
      if (available) (resource.error ? requestState.current : versionBoard.current)?.focus()
    }
  }, [id, resource.error, resource.loading, selectedVersion])

  return <StableResourceRegion key={id} holding={resource.loading || !!resource.error}>
    {resource.data
      ? <DetailContent key={`${id}:${resource.data.shown.version}:${resource.data.detail.plan.revision}`} {...resource.data}
        reload={resource.retry} receipt={receipt?.plan_id === id && receipt.revision === resource.data.detail.plan.revision ? receipt : null}
        onReceipt={setReceipt} versionBoard={versionBoard} />
      : <div ref={requestState} tabIndex={-1} className="sticky top-0 z-10 bg-paper"><RequestState {...resource} /></div>}
  </StableResourceRegion>
}

function DetailContent({ detail, shown, items, reload, receipt, onReceipt, versionBoard }: {
  detail: TripDetail; shown: PlanVersion; items: VersionInfo[]; reload: () => void
  receipt: ActionReceipt | null; onReceipt: (value: ActionReceipt) => void
  versionBoard: RefObject<HTMLDivElement | null>
}) {
  const { plan } = detail
  const snapshot = shown.snapshot
  const ref = { plan_id: plan.plan_id, version: shown.version }
  const [title, setTitle] = useState(plan.title)
  const [renaming, setRenaming] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [operation, setOperation] = useState<ScheduleAction | null>(null)
  const editing = plan.lifecycle === 'draft' || plan.lifecycle === 'scheduled'
  const copy = useIdempotent((data: CreateContent, key) => personalApi.create(data, key))
  const restore = useIdempotent((base: typeof ref, key) => personalApi.addVersion(base, { source: 'saved_version' }, plan.revision, key))
  const saveOption = useIdempotent((optionId: { id: string }, key) => personalApi.addVersion(
    ref, { source: 'saved_option', option_id: optionId.id }, plan.revision, key,
  ))
  const captureRoute = useRouteContinuation()
  const canSchedule = shown.version === plan.current_draft_version
  const calendar = plan.lifecycle === 'scheduled' && detail.scheduled && shown.version === detail.scheduled.version ? calendarText(detail.scheduled) : null

  async function rename(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try { await personalApi.rename(plan.plan_id, title, plan.revision); reload() }
    catch (err) { setError(err instanceof Error ? err.message : '名称未保存。') }
    finally { setBusy(false) }
  }

  return <div className="space-y-4">
    <Section title={plan.title} className="trip-header" action={<span className="rounded-input border border-rule px-2 py-1 text-xs font-semibold text-route">{lifecycleLabel[plan.lifecycle]}</span>}>
      <p className="trip-kicker mb-1">ALIGO / 行程档案</p>
      <p className="break-words text-sm text-ink-2">{snapshot.origin && snapshot.destination ? `${snapshot.origin} → ${snapshot.destination} · ` : ''}{days(snapshot.start_date, snapshot.end_date)}</p>
      <VersionBoard plan={plan} shown={shown} boardRef={versionBoard} />
      {receipt && <p role="status" className="text-sm font-semibold text-ok">安排操作回执：第 {receipt.version} 版 · {lifecycleLabel[receipt.lifecycle]}。不涉及预订或付款。</p>}
      <details className="mb-2 border-y border-rule">
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold text-route">版本记录（{items.length}）</summary>
        <ul className="divide-y divide-rule">
          {items.map(item => <li key={item.version}>
            <a className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 px-1 text-sm text-ink hover:bg-paper-sunken"
              aria-current={item.version === shown.version ? 'page' : undefined} href={tripHref(plan.plan_id, `?v=${item.version}`)}>
              <span>第 {item.version} 版{item.version === shown.version ? ' · 正在查看' : ''}{item.version === plan.current_draft_version ? ' · 当前草稿' : ''}{item.version === plan.scheduled_version ? ' · 实际安排' : ''}</span>
              <time className="text-xs text-ink-3" dateTime={item.created_at}>{dayTime(item.created_at)}</time>
            </a>
          </li>)}
        </ul>
      </details>
      {renaming ? <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => { void rename(e) }}>
        <input aria-label="修改行程名称" required maxLength={120} className={`${input} max-w-xs`} value={title} onChange={(e) => setTitle(e.target.value)} />
        <button className={primary} type="submit" disabled={busy}>保存名称</button>
        <button className={button} type="button" onClick={() => setRenaming(false)}>取消</button>
      </form> : <div className="mt-3 flex flex-wrap gap-2">
        <a className={button} href="#/" onClick={() => useChatStore.getState().setPendingPlan({ ref, title: plan.title })}>
          交给助手调整 <ArrowUpRight size={16} aria-hidden="true" />
        </a>
        {editing && <a className={button} href={tripHref(plan.plan_id, `/edit?v=${shown.version}`)}>手动调整</a>}
        {editing && <button className={button} type="button" onClick={() => setRenaming(true)}>修改名称</button>}
        {editing && !canSchedule && <button className={button} type="button" disabled={busy} onClick={async () => {
          const stillHere = captureRoute()
          setBusy(true); setError('')
          try {
            await restore(ref)
            if (stillHere()) { window.location.hash = tripHref(plan.plan_id); reload() }
          }
          catch (err) { setError(err instanceof Error ? err.message : '恢复旧版本失败。') }
          finally { setBusy(false) }
        }}>将此版本恢复为新草稿</button>}
        <button className={button} type="button" disabled={busy} onClick={async () => {
          const stillHere = captureRoute()
          setBusy(true); setError('')
          try {
            const result = await copy({ source: 'copy', ref })
            if (stillHere()) window.location.hash = tripHref(result.plan_id)
          }
          catch (err) { setError(err instanceof Error ? err.message : '复制失败。') }
          finally { setBusy(false) }
        }}>复制为新草稿</button>
        <FavoriteButton kind="plan" source={ref}>收藏此版本</FavoriteButton>
      </div>}
      {error && <p role="alert" className="mt-2 text-sm text-err">{error}</p>}
    </Section>
    <Section title="安排与状态">
      <p className="text-sm leading-6 text-ink-3">确认后才更新个人日历。日期已过不等于已完成；加入日历也不代表预订或付款。</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {plan.lifecycle === 'draft' && canSchedule && <button type="button" className={primary} onClick={() => setOperation('schedule')}>预检加入安排</button>}
        {plan.lifecycle === 'scheduled' && <>
          {canSchedule && shown.version !== plan.scheduled_version && <button type="button" className={primary} onClick={() => setOperation('reschedule')}>预检更新安排</button>}
          {(canSchedule || shown.version === plan.scheduled_version) && <>
            <button type="button" className={button} onClick={() => setOperation('complete')}>标记完成</button>
            <button type="button" className={button} onClick={() => setOperation('cancel')}>取消此安排</button>
          </>}
          {calendar && <button type="button" className={button} onClick={() => downloadCalendar(calendar)}>导出确定时刻（ICS）</button>}
        </>}
        {canSchedule && plan.lifecycle !== 'archived' && <button type="button" className={button} onClick={() => setOperation('archive')}>归档行程</button>}
      </div>
      {operation && <CalendarOperation detail={detail} action={operation} onClose={() => setOperation(null)} onDone={(value) => {
        if (value) onReceipt(value)
        setOperation(null); reload()
      }} />}
    </Section>
    <Section title="行程时间轴">
      <EventRows values={versionEvents(shown)} />
      {snapshot.notes && <p className="mt-3 whitespace-pre-wrap break-words border-t border-rule pt-3 text-sm text-ink-3">{snapshot.notes}</p>}
    </Section>
    <Section title="预算与证据">
      <p className="text-sm text-ink">计划预算：{snapshot.budget ? formatMoney(Number(snapshot.budget.amount), snapshot.budget.currency) : '未填写'}</p>
      {snapshot.raw_estimate && <p className="mt-1 break-words text-sm text-ink-3">旧式估算（未核验）：{snapshot.raw_estimate}</p>}
      <p className="mt-1 text-xs leading-5 text-ink-3">报价或参考价格不代表预订、付款或真实支出。</p>
      {snapshot.issues.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-warn">{snapshot.issues.map((value, index) => <li key={index}>{value}</li>)}</ul>}
      {snapshot.options.map((row, index) => <details key={row.option_id} className="mt-3 rounded-input border border-rule p-3">
        <summary className="min-h-8 cursor-pointer text-sm font-semibold">方案 {index + 1} · {snapshot.selected_option_id === row.option_id ? '已选用于此草稿' : '备选'}{row.hotel ? ` · ${row.hotel}` : ''}</summary>
        <EventRows values={row.schedule_items} />
        {row.hotel_reference_cny.length > 0 && <p className="mt-1 text-sm text-ink-2">住宿参考价（非预订报价）：{row.hotel_reference_cny.map((n) => formatMoney(Number(n))).join(' – ')}</p>}
        {row.commute && <p className="mt-1 text-sm text-ink-2">酒店到会场约 {row.commute.minutes} 分钟（地图步行估算，{dayTime(row.commute.queried_at)} 查询）</p>}
        {row.observations?.map((obs) => <p key={obs.kind} className="mt-1 text-xs text-ink-3">
          {obs.kind === 'hotel_place' ? '住宿地点' : obs.kind === 'outbound_rail' ? '去程班次' : '返程班次'} · {obs.observed_at ? `${dayTime(obs.observed_at)} 查询` : '查询时刻未记录'} · <a href={obs.source_url} className="text-accent underline" target="_blank" rel="noreferrer">核对来源</a>
        </p>)}
        {row.quotes.map((quote, q) => <p key={q} className="mt-1 text-sm leading-6 text-ink-2">
          {new Date(quote.valid_until).getTime() > Date.now() ? '查询所得报价' : '报价已过期'}：{formatMoney(Number(quote.price.amount), quote.price.currency)}
          {quote.unit === 'seat' ? ' / 座' : ' / 间夜'} · 截止 {dayTime(quote.valid_until)} · <a className="text-accent underline" href={quote.source_url} target="_blank" rel="noreferrer">核对来源</a>
        </p>)}
        <div className="mt-2 flex flex-wrap gap-2">
          {editing && row.option_id !== snapshot.selected_option_id && <button type="button" className={button} disabled={busy} onClick={async () => {
            const stillHere = captureRoute()
            setBusy(true); setError('')
            try {
              await saveOption({ id: row.option_id })
              if (stillHere()) { window.location.hash = tripHref(plan.plan_id); reload() }
            }
            catch (err) { setError(err instanceof Error ? err.message : '未能将此备选保存为新草稿。') }
            finally { setBusy(false) }
          }}>采用此备选另存一版</button>}
          {row.schedule_items.some((event) => event.kind === 'rail' && event.city === snapshot.origin) &&
            <FavoriteButton kind="rail" source={ref} option={row.option_id} direction="outbound">收藏去程</FavoriteButton>}
          {row.schedule_items.some((event) => event.kind === 'rail' && event.city === snapshot.destination) &&
            <FavoriteButton kind="rail" source={ref} option={row.option_id} direction="inbound">收藏返程</FavoriteButton>}
          {row.hotel_ref && <>
            <FavoriteButton kind="hotel" source={ref} option={row.option_id} />
            <FavoriteButton kind="place" source={ref} option={row.option_id} />
          </>}
        </div>
      </details>)}
    </Section>
    <TripSpend key={plan.plan_id} planId={plan.plan_id} />
  </div>
}

function NewTripPage() {
  const create = useIdempotent((draft: DraftContent, key) => personalApi.create({ source: 'manual', draft }, key))
  const captureRoute = useRouteContinuation()
  return <TripForm cancel="#/personal/trips" onSave={async (draft) => {
    const stillHere = captureRoute()
    const saved = await create(draft)
    if (stillHere()) window.location.hash = tripHref(saved.plan_id)
  }} />
}

function EditTripPage({ id, number }: { id: string; number?: number }) {
  const loader = useCallback(async (signal: AbortSignal) => {
    const detail = await personalApi.get(id, signal)
    return { detail, version: number ? await personalApi.version(id, number, signal) : detail.draft }
  }, [id, number])
  const resource = useLoad(loader)
  const create = useIdempotent((item: { draft: DraftContent; revision: number; version: number }, key) => personalApi.addVersion(
    { plan_id: id, version: item.version }, { source: 'manual', draft: item.draft }, item.revision, key,
  ))
  const captureRoute = useRouteContinuation(`${id}:${number}`)
  if (!resource.data) return <RequestState {...resource} />
  const { detail, version } = resource.data
  const snapshot = version.snapshot
  const option = snapshot.options.find((value) => value.option_id === snapshot.selected_option_id)
  return <TripForm key={version.version} initial={{ ...snapshot, title: detail.plan.title,
    schedule_items: [...(snapshot.schedule_items || []), ...(option?.schedule_items || [])] }} preserveEvents cancel={tripHref(id)} onSave={async (draft) => {
      const stillHere = captureRoute()
      await create({ draft, revision: detail.plan.revision, version: version.version })
      if (stillHere()) window.location.hash = tripHref(id)
    }} />
}

const tabs = [
  { path: '/personal', label: '概览', icon: CalendarDays },
  { path: '/personal/trips', label: '行程', icon: FileText },
  { path: '/personal/expenses', label: '费用', icon: Wallet },
  { path: '/personal/preferences', label: '偏好', icon: SlidersHorizontal },
  { path: '/personal/favorites', label: '收藏', icon: Bookmark },
]

export default function PersonalCenter({ path }: { path: string }) {
  const [route, query] = path.split('?')
  const match = /^\/personal\/trips\/([0-9a-f-]{36})(\/edit)?$/.exec(route)
  const selected = new URLSearchParams(query).get('v')
  const version = selected && /^[1-9]\d{0,5}$/.test(selected) ? Number(selected) : undefined
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [route])
  const newTrip = route === '/personal/trips/new'
  const title = match ? match[2] ? '调整行程' : '行程详情' : newTrip ? '新建行程草稿'
    : route === '/personal/trips' ? '我的行程' : route === '/personal/expenses' ? '差旅费用'
    : route === '/personal/preferences' ? '出行偏好' : route === '/personal/favorites' ? '我的收藏' : '个人中心'
  return <main className="min-h-0 flex-1 overflow-auto bg-paper" id="personal-main">
    <div className="mx-auto w-full max-w-[1120px] px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-5 sm:px-8 sm:pt-8">
      <nav aria-label="个人中心导航" className="personal-nav trip-subnav mb-5 flex gap-1 border-b border-rule pb-2">
        {tabs.map(({ path: target, label, icon: Icon }) => {
          const current = target === '/personal' ? route === target : route.startsWith(target)
          return <a key={target} href={`#${target}`} aria-current={current ? 'page' : undefined}
            className={`flex min-h-11 shrink-0 items-center gap-1.5 rounded-input px-3 text-sm font-semibold hover:bg-paper-sunken ${current ? 'bg-route-tint text-route' : 'text-ink-2'}`}>
            <Icon size={16} aria-hidden="true" />{label}
          </a>
        })}
      </nav>
      {(match || newTrip) && <a href={match?.[2] ? tripHref(match[1]) : '#/personal/trips'} className="mb-1 inline-flex min-h-11 items-center gap-2 text-sm text-accent">
        <ArrowLeft size={16} aria-hidden="true" />{match?.[2] ? '返回详情' : '返回行程列表'}
      </a>}
      <h1 ref={heading} tabIndex={-1} className="mb-4 font-display text-3xl font-semibold text-ink focus:outline-none">{title}</h1>
      {match ? match[2] ? <EditTripPage id={match[1]} number={version} /> : <DetailPage id={match[1]} selectedVersion={version} />
        : newTrip ? <NewTripPage /> : route === '/personal/trips' ? <TripsPage key={query || ''} initialAgenda={new URLSearchParams(query).get('view') === 'agenda'} /> : route === '/personal' ? <OverviewPage />
        : route === '/personal/expenses' ? <Expenses key={query || ''} trip={new URLSearchParams(query).get('trip') || undefined} />
        : route === '/personal/preferences' ? <Preferences /> : route === '/personal/favorites' ? <Favorites />
        : <p className="text-sm text-ink-2">这个页面不存在。<a href="#/personal" className="text-accent underline">返回个人中心</a></p>}
    </div>
  </main>
}
