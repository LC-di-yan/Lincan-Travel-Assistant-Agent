import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { ActionReceipt, ConflictIssue, OperationPreview, Replacement, ScheduleAction, TripDetail } from '../../api/personal'
import { newOperationKey, personalApi } from '../../api/personal'
import { button, dayTime, primary, tripHref } from './style'
import { EventRows } from './TripRhythm'
import { versionEvents } from './tripTimeline'
import { usePersonalResource } from './usePersonalResource'

const captions: Record<ScheduleAction, string> = {
  schedule: '加入安排', reschedule: '更新已安排版本', replace: '替换指定旧行程',
  cancel: '取消此安排', archive: '归档行程', complete: '标记完成',
}
const severity = { definite: '确定冲突', potential: '潜在冲突', unknown: '信息不足' }

export function Issues({ issues }: { issues: ConflictIssue[] }) {
  return <ul className="space-y-2">
    {issues.map((issue) => <li key={issue.id} data-severity={issue.severity} className={`trip-issue rounded-input border border-rule p-2 text-sm leading-6 ${issue.blocks_schedule ? 'text-err' : 'text-warn'}`}>
      <i aria-hidden="true" />
      <strong>{severity[issue.severity]}：</strong>{issue.message}
      {issue.other && <a className="ml-2 text-accent underline" href={tripHref(issue.other.plan_id, `?v=${issue.other.version}`)}>查看原安排</a>}
    </li>)}
  </ul>
}

function RelatedArrangement({ row }: { row: Replacement }) {
  const [open, setOpen] = useState(false)
  return <details onToggle={event => setOpen(event.currentTarget.open)} className="py-1">
    <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">{row.title || '相关行程'} · 第 {row.version} 版</summary>
    {open && <RelatedTimeline row={row} />}
  </details>
}

function RelatedTimeline({ row }: { row: Replacement }) {
  const loader = useCallback((signal: AbortSignal) => personalApi.version(row.plan_id, row.version, signal), [row.plan_id, row.version])
  const { data, loading, error, retry } = usePersonalResource(loader)
  return <>
    {loading && <p role="status" className="text-xs">正在读取原安排…</p>}
    {error && <p className="text-xs text-err"><span role="alert">{error}</span> <button type="button" className={button} onClick={retry}>重试</button></p>}
    {data && <EventRows values={versionEvents(data)} compact />}
    <a href={tripHref(row.plan_id, `?v=${row.version}`)}>查看完整版本</a>
  </>
}

export default function CalendarOperation({ detail, action, onClose, onDone }: {
  detail: TripDetail; action: ScheduleAction; onClose: () => void; onDone: (receipt?: ActionReceipt) => void
}) {
  const { plan } = detail
  const [state, setState] = useState<OperationPreview | null>(null)
  const [busy, setBusy] = useState(true)
  const [committing, setCommitting] = useState(false)
  const [error, setError] = useState('')
  const [reviewed, setReviewed] = useState<string[]>([])
  const [selected, setSelected] = useState<Replacement[]>([])
  const [reloadRequired, setReloadRequired] = useState(false)
  const [expired, setExpired] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const dismiss = useRef<HTMLButtonElement>(null)
  const headingId = useId()
  const noticeId = useId()
  const submit = useRef(false)
  const previewing = useRef(false)
  const opKey = useRef<{ id: string; key: string } | null>(null)

  const version = action === 'cancel' || action === 'complete' ? plan.scheduled_version ?? plan.current_draft_version : plan.current_draft_version
  async function load(mode: ScheduleAction, replaced: Replacement[] = []) {
    if (previewing.current || submit.current) return
    previewing.current = true
    setBusy(true); setState(null); setError(''); setReviewed([]); setExpired(false)
    try { setState(await personalApi.preview(plan.plan_id, mode, version, plan.revision, replaced)) }
    catch (err) { setError(err instanceof Error ? err.message : '预检失败。') }
    finally { previewing.current = false; setBusy(false) }
  }

  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    dismiss.current?.focus()
    let alive = true
    personalApi.preview(plan.plan_id, action, version, plan.revision).then((item) => {
      if (alive) setState(item)
    }).catch((err: unknown) => {
      if (alive) setError(err instanceof Error ? err.message : '预检失败。')
    }).finally(() => { if (alive) setBusy(false) })
    return () => { alive = false; element?.close() }
  }, [plan.plan_id, plan.revision, action, version])

  const deadline = state?.expires_at ? Date.parse(state.expires_at) : NaN
  useEffect(() => {
    if (!Number.isFinite(deadline)) return
    const timer = window.setTimeout(() => setExpired(true), Math.max(0, deadline - Date.now()))
    return () => window.clearTimeout(timer)
  }, [deadline])

  const warnings = state?.report.issues.filter((item) => item.requires_ack) || []
  const options = Array.from(new Map((state?.report.issues || []).flatMap((issue) =>
    issue.other && issue.other.revision ? [[issue.other.plan_id, issue.other] as const] : [],
  )).values())
  const replacementOptions = [...new Map([...options, ...(state?.replacements || [])].map(row => [row.plan_id, row])).values()]
  const canReplace = action === 'schedule' && replacementOptions.length > 0
  const replacementChanged = canReplace && (selected.length !== (state?.replacements.length || 0) ||
    selected.some(row => !state?.replacements.some(old => old.plan_id === row.plan_id && old.version === row.version)))
  const ready = state?.report.can_commit && state.operation_id && !busy && !reloadRequired && !expired &&
    Number.isFinite(deadline) && !replacementChanged && warnings.every(issue => reviewed.includes(issue.id))
  const proposed = ['schedule', 'reschedule', 'replace'].includes(state?.action || action)
  const related = state?.replacements.length ? state.replacements : options
  const close = () => { if (!submit.current) onClose() }

  async function commit() {
    const id = state?.operation_id
    if (!id || !ready || submit.current || previewing.current) return
    if (Date.now() >= deadline) { setExpired(true); return }
    submit.current = true
    setBusy(true); setCommitting(true); setError('')
    if (opKey.current?.id !== id) opKey.current = { id, key: newOperationKey() }
    try {
      const receipt = await personalApi.commit(plan.plan_id, id, reviewed, opKey.current.key)
      onDone(receipt)
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败。')
      if (err && typeof err === 'object' && 'status' in err && [409, 410, 412].includes(Number(err.status))) setReloadRequired(true)
    } finally { submit.current = false; setBusy(false); setCommitting(false) }
  }

  return <dialog ref={dialog} aria-labelledby={headingId} aria-describedby={noticeId} onCancel={(e) => { e.preventDefault(); close() }}
    className="trip-header m-auto max-h-[88dvh] w-[min(94vw,56rem)] overflow-auto rounded-input border border-rule bg-paper-raised p-4 text-ink shadow-lg backdrop:bg-black/40 sm:p-6">
    <p className="trip-kicker mb-1">ALIGO / 安排预检</p>
    <h2 id={headingId} className="font-display text-2xl font-semibold">{captions[state?.action || action]} · 预检</h2>
    <p className="trip-calendar-status" id={noticeId}><strong>预检不是安排。</strong> 当前日历未由这一步修改；只有你主动确认，并收到成功回执后，本次变更才算完成。</p>
    <p className="mt-2 break-words text-sm leading-6 text-ink-2">「{plan.title}」第 {version} 版。安排只更新个人日历，不购票、不订房、不记账。取消或归档不会删除费用和历史版本。</p>
    {busy && <p role="status" className="mt-3 text-sm text-ink-3">{committing ? '正在确认…' : '正在检查安排…'}</p>}
    <div className="trip-change-board">
      <section aria-label="原安排">
        <h3>原安排</h3>
        {detail.scheduled ? <><p className="mb-2 text-sm">本行程实际安排：第 {detail.scheduled.version} 版</p>
          <EventRows values={versionEvents(detail.scheduled)} compact /></>
          : <p className="text-sm text-ink-3">本行程目前未占用日历。</p>}
        {related.length > 0 && <ul className="mt-2 border-t border-rule">
          {related.map(row => <li key={row.plan_id}><RelatedArrangement row={row} /></li>)}
        </ul>}
      </section>
      <section data-proposed aria-label="拟变更">
        <h3>拟变更</h3>
        <p className="mb-2 text-sm">{proposed ? `用第 ${version} 版草稿更新日历` : `${captions[state?.action || action]} · 第 ${version} 版`}</p>
        {proposed ? <EventRows values={versionEvents(detail.draft)} compact />
          : <p className="text-sm text-ink-3">确认后释放本行程安排，草稿与历史版本继续保留。</p>}
      </section>
    </div>
    {state && <div className="mt-4 space-y-3">
      {state.replacements.length > 0 && <div className="rounded-input border border-rule bg-paper-sunken p-3">
        <p className="text-sm font-semibold">确认后，以下安排将被替换；原资料仍保留：</p>
        <ul className="mt-1 list-disc pl-4 text-sm">{state.replacements.map((item) =>
          <li key={item.plan_id}>{item.title} · 第 {item.version} 版</li>)}</ul>
      </div>}
      {state.report.issues.length ? <Issues issues={state.report.issues} /> : <p className="text-sm text-ok">按当前资料未发现阻碍本次操作的问题。</p>}
      {canReplace && <fieldset className="space-y-2 rounded-input border border-rule p-3">
        <legend className="px-1 text-sm font-semibold">也可以指定要替换的已安排行程</legend>
        {replacementOptions.map((item) => <label key={item.plan_id} className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4" checked={selected.some((row) => row.plan_id === item.plan_id)}
            onChange={(e) => setSelected(e.target.checked ? [...selected, item] : selected.filter((row) => row.plan_id !== item.plan_id))} />
          {item.title} · 第 {item.version} 版
        </label>)}
        <button type="button" className={button} disabled={busy || reloadRequired || selected.length > 6 || (!selected.length && state.action !== 'replace')}
          onClick={() => { void load(selected.length ? 'replace' : action, selected) }}>按所选替换重新预检</button>
        {replacementChanged && <p className="text-sm text-warn">所选替换项已改变，须重新预检。</p>}
      </fieldset>}
      {state.report.can_commit && warnings.map((issue) => <label key={issue.id} className="flex min-h-11 items-start gap-2 text-sm leading-5">
        <input type="checkbox" className="mt-0.5 h-4 w-4" checked={reviewed.includes(issue.id)}
          onChange={(e) => setReviewed(e.target.checked ? [...reviewed, issue.id] : reviewed.filter((key) => key !== issue.id))} />
        我已核对：{issue.message}
      </label>)}
      {state.expires_at && <p className="text-xs text-ink-3">本次确认有效至 {dayTime(state.expires_at)}（北京时间）。</p>}
    </div>}
    {error && <p role="alert" className="mt-3 text-sm text-err">{error}</p>}
    {expired && <p role="status" className="mt-3 text-sm text-warn">本次预检已过有效期，不能确认。</p>}
    <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-rule pt-3">
      <button ref={dismiss} type="button" className={button} onClick={close} disabled={committing}>{action === 'schedule' ? '保留草稿，不安排' : '取消操作'}</button>
      {expired && !reloadRequired && <button type="button" className={button} disabled={busy}
        onClick={() => { void load(selected.length ? 'replace' : action, selected) }}>重新预检</button>}
      {error && (reloadRequired
        ? <button type="button" className={button} onClick={() => onDone()}>刷新行程资料</button>
        : !state && <button type="button" disabled={busy} className={button} onClick={() => { void load(action) }}>重新预检</button>)}
      {state?.operation_id && <button type="button" className={primary}
        disabled={!ready} onClick={() => { void commit() }}>确认{captions[state.action]}</button>}
    </div>
  </dialog>
}
