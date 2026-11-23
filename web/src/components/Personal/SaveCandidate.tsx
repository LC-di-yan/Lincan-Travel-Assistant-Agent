import { useRef, useState } from 'react'
import { BookmarkPlus, ChevronDown, ExternalLink } from 'lucide-react'
import type { OrchestrationResult } from '../../api/types'
import { type ActionReceipt, type CandidateContent, type ConflictIssue, newOperationKey, personalApi } from '../../api/personal'
import { Issues } from './CalendarOperation'
import { asRecord } from '../../utils/resultData'
import { proposalLetter } from '../../utils/proposalComparison'

function IssueDisclosure({ title, issues }: { title: string; issues: ConflictIssue[] }) {
  if (!issues.length) return null
  const definite = issues.filter(issue => issue.severity === 'definite').length
  const potential = issues.filter(issue => issue.severity === 'potential').length
  const details = [definite && `${definite} 项确定冲突`, potential && `${potential} 项潜在冲突`,
    issues.length > definite + potential && `${issues.length - definite - potential} 项待核验`].filter(Boolean).join(' · ')
  return <details className="group rounded-input border border-rule bg-paper p-2">
    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-1 text-left text-sm focus-visible:outline-2 focus-visible:outline-route [&::-webkit-details-marker]:hidden">
      <span><strong className="block text-ink">{title}</strong><span className="text-ink-3">{details}</span></span>
      <ChevronDown size={16} aria-hidden="true" className="shrink-0 text-route group-open:rotate-180" />
    </summary>
    <div className="mt-2"><Issues issues={issues} /></div>
  </details>
}

export default function SaveCandidate({ id, result, confirmedOptionId }: { id?: string; result: OrchestrationResult; confirmedOptionId?: string }) {
  const [override, setOption] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState<ActionReceipt | null>(null)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [advisory, setAdvisory] = useState(result.personal_conflicts)
  const pending = useRef(false)
  const keys = useRef(new Map<string, string>())
  const alternatives = Array.isArray(result.trip_plan?.alternatives)
    ? result.trip_plan.alternatives.map((value, index) => {
      const row = asRecord(value)
      return { id: typeof row.id === 'string' ? row.id : '', index, validated: row.status === 'validated' }
    }).filter(row => row.id) : []
  const snapshotOption = alternatives.find(row => row.id === result.trip_plan?.selected_proposal)
  const option = override ?? confirmedOptionId ?? ''
  const target = alternatives.find(row => row.id === option) ?? snapshotOption
  const snapshotApplies = !option || option === snapshotOption?.id
  const base = result.candidate_base

  async function save(append: boolean) {
    if (pending.current || !result.candidate_ref || !result.candidate_session_id) return
    pending.current = true
    setBusy(true)
    setError('')
    const payload: CandidateContent = { source: 'candidate', candidate_ref: result.candidate_ref,
      session_id: result.candidate_session_id, ...(option ? { option_id: option } : {}) }
    const mode = `${append}:${option}`
    const key = keys.current.get(mode) || newOperationKey()
    keys.current.set(mode, key)
    try {
      const receipt = append && base && result.candidate_base_revision
        ? await personalApi.addVersion(base, payload, result.candidate_base_revision, key)
        : await personalApi.create(payload, key)
      setSaved(receipt)
      window.dispatchEvent(new Event('personal-trips-updated'))
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败，请重试。')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  return <section id={id} tabIndex={-1} aria-label="保存行程草稿" className="proposal-save-panel mt-3 scroll-mt-3 rounded-card border border-rule bg-paper-raised p-3.5 focus:outline-2 focus:outline-route">
    <h4 className="font-semibold text-ink">保留这份行程</h4>
    <p className="mt-1 text-sm leading-6 text-ink-3">存入个人中心，不会安排日历、购票或记账。切换预览不会改变下方的保存选项。</p>
    {snapshotApplies && advisory?.issues.length ? <div className="mt-2 space-y-2">
      <p className="text-sm text-ink-2">这些提示不影响保存草稿；加入安排前会再次检查。</p>
      <IssueDisclosure title="与已有安排有关的提示" issues={advisory.issues.filter(issue => issue.other)} />
      <IssueDisclosure title="本行程时间与信息提示" issues={advisory.issues.filter(issue => !issue.other)} />
    </div> : null}
    {snapshotApplies && !advisory && result.candidate_ref && result.candidate_session_id && <button type="button" className="min-h-11 text-left text-sm font-semibold text-accent underline"
      disabled={checking} onClick={async () => {
        setError(''); setChecking(true)
        try { setAdvisory(await personalApi.conflicts(result.candidate_ref!, result.candidate_session_id!)) }
        catch (err) { setError(err instanceof Error ? err.message : '暂时无法检查日历。') }
        finally { setChecking(false) }
      }}>{checking ? '正在检查…' : '与已安排行程比较'}</button>}
    {snapshotApplies && advisory && !advisory.issues.length && <p className="mt-2 text-sm text-ok">按生成时的资料，未发现安排冲突。</p>}
    {saved ? <p role="status"><a href={`#/personal/trips/${saved.plan_id}`} className="mt-1 flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent">
      已保存第 {saved.version} 版草稿，前往查看 <ExternalLink size={14} aria-hidden="true" />
    </a></p> : <>
      {alternatives.length > 0 && <label className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-2">
        保存时采用
        <select className="min-h-11 rounded-input border border-rule-strong bg-paper px-2" value={option} onChange={(e) => setOption(e.target.value)} disabled={busy}>
          <option value="">{snapshotOption ? `保留生成时的方案 ${proposalLetter(snapshotOption.index)}` : '保留全部候选，不指定方案'}</option>
          {alternatives.map(row => <option key={row.id} value={row.id}>方案 {proposalLetter(row.index)}{row.validated ? '' : ' · 待核验'}</option>)}
        </select>
      </label>}
      {alternatives.length > 0 && <p className="mt-1 text-sm text-ink-2">
        {target ? `本次草稿采用方案 ${proposalLetter(target.index)}，保留其他候选。` : '本次草稿保留候选，不会确认任何一个方案。'}
        {target && !target.validated && ' 此候选仍待核验。'}
      </p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {base && result.candidate_base_revision && <button type="button" disabled={busy} onClick={() => { void save(true) }}
          className="min-h-11 rounded-input border border-accent px-3 text-sm font-semibold text-accent hover:bg-paper-sunken disabled:opacity-60">
          保存为原行程的新版本
        </button>}
        <button type="button" disabled={busy} onClick={() => { void save(false) }}
          className="flex min-h-11 items-center gap-1.5 rounded-input border border-rule-strong px-3 text-sm font-semibold text-ink hover:bg-paper-sunken disabled:opacity-60">
          <BookmarkPlus size={16} aria-hidden="true" /> {busy ? '正在保存…' : base ? '另存为新草稿' : '保存为草稿'}
        </button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-err">{error}</p>}
    </>}
  </section>
}
