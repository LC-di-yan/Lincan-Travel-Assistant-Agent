import { useId, useState } from 'react'
import { ArrowRight, ChevronDown, Columns2, FileText, MapPin } from 'lucide-react'
import { asRecord } from '../../utils/resultData'
import { formatMoney } from '../../utils/money'
import { publicLink } from '../../utils/flightEvidence'
import { compareProposalCosts, comparisonPair, proposalLetter, verifiedCost } from '../../utils/proposalComparison'
import './proposal.css'

const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []
const label = (value: unknown): string => typeof value === 'string' ? value : ''
const records = (value: unknown) => Array.isArray(value) ? value.map(asRecord) : []
const dateTime = (value: unknown) => label(value).slice(0, 16).replace('T', ' ')
const costLabels: Record<string, string> = { outbound: '去程', inbound: '返程', hotel: '住宿', other: '其他必要费用' }
const budgetLabels: Record<string, string> = { within: '预算内', exceeds: '超过预算', unverified: '未能确认符合预算', not_set: '未设总预算' }

export interface ProposalActions {
  onSelect?: (index: number, optionId: string) => void
  confirmedOptionId?: string
  requestState?: 'pending' | 'unconfirmed'
  savePanelId?: string
  historical?: boolean
}

interface PlanCell { title: string; note?: string; stations?: string; signature?: string }
interface PlanRow { key: string; title: string; read: (option: Record<string, unknown>) => PlanCell }

function amountText(value: unknown) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function costCell(option: Record<string, unknown>): PlanCell {
  const subtotals = Object.entries(asRecord(option.known_subtotals))
    .filter(([currency, amount]) => /^[A-Z]{3}$/.test(currency) && /^\d+(\.\d+)?$/.test(amountText(amount)))
    .sort(([a], [b]) => a.localeCompare(b))
  return {
    title: subtotals.map(([currency, amount]) => `${currency} ${amountText(amount)}`).join(' + ') || '金额待核验',
    note: [verifiedCost(option) ? '计划费用' : subtotals.length ? '仅已知费用小计' : '', budgetLabels[label(option.budget_status)]].filter(Boolean).join(' · '),
    signature: subtotals.length ? subtotals.map(([code, amount]) => `${code}:${Number(amount)}`).join('|') : undefined,
  }
}

function legCell(value: unknown): PlanCell {
  const leg = asRecord(value)
  const train = label(leg.train_no)
  const stations = [label(leg.from_station), label(leg.to_station)].filter(Boolean).join(' → ')
  const departs = dateTime(leg.departs)
  const arrives = dateTime(leg.arrives)
  const times = departs.length === 16 && arrives.length === 16 && departs.slice(0, 10) === arrives.slice(0, 10)
    ? `${departs.slice(0, 10)} · ${departs.slice(11)} → ${arrives.slice(11)}`
    : [departs, arrives].filter(Boolean).join(' → ')
  return train ? { title: train, note: times || '时刻待核验', stations, signature: [train, stations, times].join('|') } : { title: '班次待核验' }
}

function walkMinutes(option: Record<string, unknown>) {
  const minutes = asRecord(option.commute).duration_min
  return typeof minutes === 'number' && Number.isInteger(minutes) && minutes >= 0 ? minutes : null
}

function planRows(request: Record<string, unknown>, options: Record<string, unknown>[]): PlanRow[] {
  const rows: PlanRow[] = [
    { key: 'cost', title: '费用', read: costCell },
    { key: 'out', title: '去程', read: option => legCell(option.outbound) },
  ]
  if (request.one_way !== true) rows.push({ key: 'back', title: '返程', read: option => legCell(option.inbound) })
  if ((typeof request.hotel_nights === 'number' && request.hotel_nights > 0) || options.some(o => !!asRecord(o.hotel).name)) {
    rows.push({
      key: 'hotel', title: '住宿', read: option => {
        const hotel = asRecord(option.hotel)
        const name = label(hotel.name)
        return { title: name || '住宿待核验', signature: name ? label(hotel.id) || name : undefined }
      },
    })
  }
  if (request.meeting_place || options.some(o => o.commute)) rows.push({
    key: 'walk', title: '到会场', read: option => {
      const duration = walkMinutes(option)
      return duration !== null
        ? { title: `步行约 ${duration} 分钟`, signature: String(duration), note: '地图估算' }
        : { title: '通勤待核验' }
    },
  })
  return rows
}

function Comparison({ options, rows, indices, active, differencesOnly }: {
  options: Record<string, unknown>[]; rows: PlanRow[]; indices: readonly [number, number]; active: number; differencesOnly: boolean
}) {
  const [left, right] = indices
  const a = proposalLetter(left)
  const b = proposalLetter(right)
  const cost = compareProposalCosts(options[left], options[right])
  const delta = cost && (cost.delta === 0 ? '两份方案计划费用相同'
    : `${b} 比 ${a} ${cost.delta < 0 ? '少' : '多'} ${formatMoney(Math.abs(cost.delta), cost.currency)}（计划费用）`)
  const walkA = walkMinutes(options[left])
  const walkB = walkMinutes(options[right])
  const walkDelta = walkA !== null && walkB !== null ? walkB - walkA : 0
  const compared = rows.map(row => {
    const cells = indices.map(i => row.read(options[i]))
    const [first, second] = cells
    const comparable = row.key === 'cost' ? cost !== null : first.signature !== undefined && second.signature !== undefined
    const changed = comparable && (first.signature !== second.signature || first.note !== second.note)
    return { row, cells, changed, missing: !comparable }
  }).filter(row => !differencesOnly || row.changed || row.missing)
  return <div className="proposal-compare">
    <table aria-label={`方案 ${a} 与 ${b} 的差异`}>
      <thead><tr><th scope="col">对照项</th>
        {indices.map(i => <th scope="col" key={i} data-preview={active === i}>方案 {proposalLetter(i)}
          {active === i && <small>预览中</small>}
        </th>)}
      </tr></thead>
      <tbody>{compared.map(({ row, cells, changed, missing }) => {
        const [first, second] = cells
        return <tr key={row.key} data-difference={changed}>
          <th scope="row">{row.title}
            {changed && <small>有差异</small>}
            {missing && <small>不直接比较</small>}
          </th>
          {cells.map((cell, i) => <td key={i} data-preview={active === indices[i]}><strong>{cell.title}</strong>
            {cell.stations && first.stations !== second.stations && <small>{cell.stations}</small>}
            {cell.note && <small>{cell.note}</small>}
          </td>)}
        </tr>
      })}
      {compared.length === 0 && <tr><td colSpan={3}>已核对的对比项相同。</td></tr>}
      </tbody>
    </table>
    <p className="proposal-delta">
      <span>{delta || '只有费用齐全、范围相同且币种一致，才计算费用差。'}</span>
      {walkDelta !== 0 && <span>{b} 到会场比 {a} {walkDelta > 0 ? '多' : '少'}走约 {Math.abs(walkDelta)} 分钟</span>}
    </p>
  </div>
}

function Evidence({ option, request }: { option: Record<string, unknown>; request: Record<string, unknown> }) {
  const legs: [string, unknown][] = [['去程', option.outbound]]
  if (request.one_way !== true) legs.push(['返程', option.inbound])
  const hotel = asRecord(option.hotel)
  const walk = walkMinutes(option)
  const costs = records(option.cost_items)
  const reasons = strings(option.reasons)
  const issues = strings(option.issues)
  return <div className="proposal-evidence">
    <div>
      <h5>行程时刻 <span>时刻与地点以来源为准</span></h5>
      <ol className="proposal-dayrail">{legs.map(([name, value]) => {
        const leg = asRecord(value)
        return <li key={name}>
          <p className="proposal-day-label">{dateTime(leg.departs).slice(0, 10) || '日期待核验'} · {name}</p>
          <strong>{label(leg.train_no) || '班次待核验'}</strong>
          {leg.train_no ? <p>{[label(leg.from_station), label(leg.to_station)].filter(Boolean).join(' → ')}</p> : null}
          {leg.train_no ? <small>{legCell(leg).note} · 12306</small> : null}
        </li>
      })}</ol>
      {label(hotel.name) && <p className="proposal-place"><MapPin size={15} aria-hidden="true" />
        <span>{label(hotel.name)} <small>高德地点{label(hotel.address) && ` · ${label(hotel.address)}`}</small></span>
      </p>}
      {walk !== null && <p className="proposal-place">到会场：步行约 {walk} 分钟 · 高德估算</p>}
    </div>
    <div>
      <h5>费用依据 <span>不等于实付款</span></h5>
      {costs.length ? <dl className="proposal-cost-items">{costs.map((item, i) => {
        const source = publicLink(item.source_url)
        return <div key={i}>
        <dt>{costLabels[label(item.kind)] || '费用'}</dt>
        <dd>{item.amount == null ? '待核验' : `${label(item.currency)} ${amountText(item.amount)}`}
          {item.amount != null && <small>{item.quality === 'user_budget' ? '用户给定额度' : '报价'}
            {item.queried_at ? ` · 查询于 ${dateTime(item.queried_at)}` : ''}</small>}
          {source && <a className="inline-flex min-h-11 items-center text-xs font-semibold text-route underline"
            href={source} target="_blank" rel="noopener noreferrer">核对报价来源</a>}
        </dd>
      </div>})}</dl> : <p>尚无可核验的费用明细。</p>}
      {(reasons.length > 0 || issues.length > 0) && <ul className="proposal-notes">
        {reasons.map((value, i) => <li key={`reason-${i}`}>{value}</li>)}
        {issues.map((value, i) => <li key={`issue-${i}`} data-warning>{value}</li>)}
      </ul>}
    </div>
  </div>
}

export default function TripPlanCard({ data, actions }: { data: Record<string, unknown>; actions?: ProposalActions }) {
  const plan = asRecord(data.trip_plan)
  const request = asRecord(plan.request)
  const budget = asRecord(request.budget)
  const recommended = label(asRecord(plan.recommended).id)
  const validation = label(asRecord(plan.validation).note)
  const options = records(plan.alternatives)
  const confirmed = actions?.confirmedOptionId || label(plan.selected_proposal)
  const confirmedIndex = options.findIndex(o => o.id === confirmed && o.status === 'validated')
  const issues = records(plan.issues).map(issue => label(issue.message)).filter(Boolean)
  const [preview, setPreview] = useState<{ index: number; optionId: string; direction: number } | null>(null)
  const [compare, setCompare] = useState(false)
  const [pairChoice, setPairChoice] = useState<readonly [string, string] | null>(null)
  const [differencesOnly, setDifferencesOnly] = useState(false)
  const [details, setDetails] = useState(false)
  const id = useId()
  const defaultIndex = confirmedIndex >= 0 ? confirmedIndex : Math.max(0, options.findIndex(o => o.id === recommended))
  const previewIndex = preview?.optionId ? options.findIndex(o => o.id === preview.optionId) : preview?.index ?? -1
  const active = previewIndex >= 0 && previewIndex < options.length ? previewIndex : defaultIndex
  const option = options[active]
  const letter = proposalLetter(active)
  const keys = options.map((row, index) => label(row.id) ? `id:${row.id}` : `index:${index}`)
  const chosen = pairChoice ? [keys.indexOf(pairChoice[0]), keys.indexOf(pairChoice[1])] as const : null
  const pair = chosen && chosen[0] >= 0 && chosen[1] >= 0 && chosen[0] !== chosen[1] ? chosen : comparisonPair(options.length, active)
  const rows = planRows(request, options)
  const editable = option?.status === 'validated' && !!label(option.id)
  const route = [label(request.origin), label(request.destination)].filter(Boolean)
  const dates = [label(request.depart_date), label(request.resolved_return_date)].filter(Boolean)

  return <section className="proposal-shell" aria-label="差旅方案对比">
    <header className="proposal-heading">
      <p className="proposal-kicker"><i /> ALIGO <span>/</span> 方案航图</p>
      <h3>{route.length ? route.join(' → ') : '差旅方案'}</h3>
      <p className="proposal-meta">
        {dates.length > 0 && <span>{dates.join(' 至 ')}</span>}
        {amountText(budget.amount) && <span>总预算 {label(budget.currency)} {amountText(budget.amount)}</span>}
        <span>{options.length} 份候选</span>
      </p>
    </header>
    {!option ? <div className="proposal-empty">
      <strong>暂无可对比的候选</strong>
      <p>{label(data.answer) || '补充行程条件或核验结果后，再生成方案。'}</p>
    </div> : <>
      <div className="proposal-controls">
        <div className="proposal-tabs" role="group" aria-label="预览方案">
          {options.map((row, index) => <button type="button" key={index} aria-pressed={active === index}
            aria-label={`预览方案 ${proposalLetter(index)}`} aria-controls={id + '-sheet'}
            onClick={() => { if (index !== active) setPreview({ index, optionId: label(row.id), direction: index > active ? 1 : -1 }) }}>
            <b aria-hidden="true">{proposalLetter(index)}</b>
            <span>{label(row.id) && row.id === recommended ? '推荐' : row.status === 'validated' ? '备选' : '待核验'}</span>
          </button>)}
        </div>
        {pair && <button type="button" className="proposal-compare-toggle" aria-expanded={compare}
          aria-controls={id + '-compare'} onClick={() => setCompare(!compare)}>
          <Columns2 size={16} aria-hidden="true" />{compare ? '收起对比' : '对比差异'}
        </button>}
      </div>
      <div id={id + '-compare'} hidden={!compare || !pair}>
        {compare && pair && <>
          <div className="proposal-compare-controls">
            {options.length > 2 && pair.map((position, side) => <label key={side}>{side === 0 ? '左对比方案' : '右对比方案'}
              <select value={keys[position]} onChange={event => setPairChoice(side === 0
                ? [event.target.value, keys[pair[1]]] : [keys[pair[0]], event.target.value])}>
                {options.map((_, index) => <option key={index} value={keys[index]} disabled={pair[1 - side] === index}>方案 {proposalLetter(index)}</option>)}
              </select>
            </label>)}
            <button type="button" aria-pressed={differencesOnly} onClick={() => setDifferencesOnly(!differencesOnly)}>
              {differencesOnly ? '查看全部对比项' : '只看差异'}
            </button>
            {differencesOnly && <span>保留不可直接比较的待核验项。</span>}
          </div>
          <Comparison options={options} rows={rows} indices={pair} active={active} differencesOnly={differencesOnly} />
        </>}
      </div>
      <div className="proposal-sheet" id={id + '-sheet'}>
        <div className="proposal-sheet-top">
          <span className="proposal-kicker">当前预览 / {letter}</span>
          <span className="proposal-tag" data-warning={!editable}>{editable ? '方案已核验' : '候选待核验'}</span>
        </div>
        <div key={active} className="proposal-preview" data-step={preview?.direction}>
          <dl aria-label={`方案 ${letter} 概览`}>
            {rows.filter(row => row.key !== 'back').map(row => {
              const cell = row.read(option)
              return <div key={row.key}><dt>{row.title}</dt><dd>{cell.title}</dd>{cell.note && row.key !== 'out' && <dd><small>{cell.note}</small></dd>}</div>
            })}
          </dl>
        </div>
        <button type="button" className="proposal-expand" aria-expanded={details}
          aria-controls={id + '-evidence'} onClick={() => setDetails(!details)}>
          <FileText size={16} aria-hidden="true" />
          {details ? '收起行程与费用明细' : '展开行程与费用明细'}
          <ChevronDown size={16} className="proposal-chevron" aria-hidden="true" />
        </button>
        <div id={id + '-evidence'} hidden={!details}>
          {details && <Evidence option={option} request={request} />}
        </div>
      </div>
      <footer className="proposal-footer">
        <div role="status">
          {confirmedIndex >= 0 && <strong className="proposal-confirmed">{actions?.historical ? '当时已确认' : '已确认'}方案 {proposalLetter(confirmedIndex)}</strong>}
          {actions?.requestState === 'pending' ? <strong className="block">等待确认回执…</strong>
            : actions?.requestState === 'unconfirmed' ? <strong className="block">未收到确认回执，选择未变更</strong>
              : confirmedIndex < 0 && <strong>预览不等于确认</strong>}
          <small>{confirmedIndex >= 0 ? '切换预览不会更改选择' : '确认不预订、不保存'}</small>
        </div>
        {actions?.onSelect && editable && active < 3 && active !== confirmedIndex && <button type="button" className="proposal-select"
          onClick={() => actions.onSelect?.(active + 1, label(option.id))} aria-label={`选择方案 ${active + 1}`}>
          确认方案 {letter} <ArrowRight size={15} aria-hidden="true" />
        </button>}
        {actions?.savePanelId && <button type="button" className="proposal-save-jump" onClick={() => {
          document.getElementById(actions.savePanelId!)?.focus()
        }}>前往保存草稿</button>}
      </footer>
    </>}
    {(issues.length > 0 || validation || (option && label(data.answer))) && <details className="proposal-context">
      <summary>规划说明与待核验项{issues.length > 0 && `（${issues.length}）`}</summary>
      {option && label(data.answer) && <p>{label(data.answer)}</p>}
      {issues.length > 0 && <ul>{issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
      {validation && <p>{validation}</p>}
    </details>}
  </section>
}
