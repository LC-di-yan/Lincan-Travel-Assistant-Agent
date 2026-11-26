import { asRecord } from '../../utils/resultData'
import { currencyCode, expenseTotals, isCompactExpense, originalAmount } from '../../utils/expenseEvidence'
import { evidenceSources, evidenceText } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult } from './FlightResult'
import { AnimatedNumber } from '../effects/AnimatedNumber'

type ExpenseItem = Record<string, unknown>
const records = (value: unknown) => Array.isArray(value) ? value.map(asRecord).filter(item => Object.keys(item).length) : []

function Items({ items, label }: { items: ExpenseItem[]; label: string }) {
  return <ul className="fdr-expense-lines" aria-label={label}>
    {items.map((item, index) => <li key={index}>
      <div><strong>{evidenceText(item.description) || evidenceText(item.category) || '费用明细'}</strong>
        <small>{[evidenceText(item.date), item.description && evidenceText(item.category)].filter(Boolean).join(' · ')}</small>
      </div>
      <b>{originalAmount(item.amount, item.currency)}</b>
    </li>)}
  </ul>
}

function Totals({ values, label, raw }: { values: ReturnType<typeof expenseTotals>; label: string; raw: Record<string, unknown> }) {
  return <div className="fdr-expense-totals">
    <h4>{label} <small>保留原币，不换算</small></h4>
    <ul>{values.map(({ currency, display }, index) => {
      const amount = Number(raw[currency])
      return <li key={index}>
        <strong>{Number.isFinite(amount) && currency
          ? <>{currency} <AnimatedNumber value={amount} precision={2} className="min-w-0" /></>
          : display}</strong>
      </li>
    })}</ul>
  </div>
}

export function ExpenseCard({ data, onConfirm, onDecline, fresh = false, submitting = false, cancelling = false }: {
  data: Record<string, unknown>; onConfirm?: () => void; onDecline?: () => void; fresh?: boolean; submitting?: boolean; cancelling?: boolean
}) {
  const action = data.action
  const answer = evidenceText(data.answer)
  const summary = asRecord(data.summary)
  const expense = asRecord(data.expense)
  const items = records(data.expenses)
  const lines = items.length ? items : Object.keys(expense).length ? [expense] : []
  if (action === 'declined' || action === 'clarify') {
    return <section className="flight-result" data-agent="expense_tracker" aria-label="费用回执">
      <p className="fdr-summary" role="status">{answer}</p>
    </section>
  }
  if (lines.length === 1 && isCompactExpense(data)) {
    const row = lines[0]
    const name = evidenceText(row.category) || evidenceText(row.description) || '费用'
    const date = evidenceText(row.date)
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai',
      year: 'numeric', month: '2-digit', day: '2-digit' }).format()
    const amount = originalAmount(row.amount, row.currency).replace(/^CNY ([\d.]+)$/, '¥$1')
    const status = action === 'record' ? '已记入账本' : cancelling ? '正在取消，等待账本确认'
      : submitting ? '正在提交，等待账本确认' : onConfirm ? '待你确认 · 尚未记入账本' : '预览快照 · 当时未写入'
    return <section className="flight-result fdr-spoken-expense" data-agent="expense_tracker" aria-label="费用回执">
      <div className="fdr-spoken-expense-detail">
        <div>
          <h3>{name}</h3>
          {date && <p>日期：{date === today && onConfirm ? '今天 · ' : ''}<time dateTime={date}>{date}</time></p>}
        </div>
        <strong>{amount}</strong>
      </div>
      <div className="fdr-expense-actions">
        <span role="status">{status}</span>
        {onConfirm && !submitting && !cancelling && <div className="fdr-expense-buttons">
          <button type="button" onClick={onConfirm}>记入账本</button>
          {onDecline && <button type="button" className="fdr-expense-decline" onClick={onDecline}>不记</button>}
        </div>}
      </div>
    </section>
  }
  const pending = action === 'preview'
  const failed = action === 'error' || action === 'unknown'
  const committed = action === 'record' || action === 'update' || action === 'delete'
  const query = !pending && !committed && !failed
  const scope = asRecord(data.applied_scope)
  const scopeLabel = evidenceText(scope.label)
  const scopeMode = evidenceText(scope.mode)
  const fallbackSource = pending ? '当前会话的操作预览' : failed ? '本次账本操作提示' : '当前费用账本'
  const sources = evidenceSources([{ title: fallbackSource }], data.sources, summary.sources)
  const operation = data.operation === 'update' ? '修改费用' : data.operation === 'delete' ? '删除费用' : '新增费用'
  const title = pending ? operation : action === 'delete' ? '费用已删除' : action === 'update' ? '费用已修改'
    : action === 'record' ? '费用已记录' : failed ? '费用操作未确认成功' : '费用汇总'
  const totals = query ? expenseTotals(summary.totals_by_currency, { amount: summary.total, currency: summary.currency })
    : expenseTotals(data.totals_by_currency, { amount: data.total_after, currency: data.total_currency ?? expense.currency })
  const rawTotals = asRecord(query ? summary.totals_by_currency : data.totals_by_currency)
  const categories = asRecord(summary.by_category_by_currency)
  const onlyCurrency = totals.length === 1 ? totals[0].currency : ''
  const flat = asRecord(summary.by_category)
  const categoryGroups = Object.keys(categories).length ? Object.entries(categories)
    : Object.keys(flat).length && onlyCurrency && currencyCode(summary.currency) === onlyCurrency ? [[onlyCurrency, flat] as const] : []
  const recent = records(summary.items).slice(-5).reverse()

  return <FlightResult agent="expense_tracker" kind="费用回执" title={title}
    meta={query && typeof summary.count === 'number'
      ? <span>{summary.count} 笔{scopeMode === 'filtered' && scopeLabel ? ` · 已筛选：${scopeLabel}` : ''}</span>
      : undefined}>
    <EvidenceBand
      label={pending ? '预览' : committed ? '已确认' : failed ? '未确认' : '账本查询'}
      status={pending ? submitting ? '已提交确认 · 等待账本回执' : onConfirm ? '待确认 · 账本未修改' : '预览快照 · 当时未写入'
        : committed ? '账本已更新' : failed ? '未收到成功回执' : '按原币分别显示'}
      sources={sources} tone={committed ? 'confirmed' : pending || failed ? 'warning' : 'neutral'}
      live={submitting || fresh && committed} stamp={fresh && committed}>
      {query && scopeMode === 'filtered' && scopeLabel && <p>查询范围：{scopeLabel}（其余期间与类别未计入）</p>}
      {query && !scopeMode && <p><small>历史回执未标注查询范围，未按当前口径重新计算。</small></p>}
      {query && scopeMode === 'unresolved' && <p>未确认查询范围，因此没有返回账本总计。</p>}
      {pending && !onConfirm && !submitting && <p>当前不能在此确认，请以最新回执为准。</p>}
    </EvidenceBand>
    {lines.length > 0 && !query && !failed && <Items items={lines} label={pending && operation !== '新增费用' ? '原账本记录' : '费用原币明细'} />}
    {query && summary.count !== 0 && totals.length > 0 && <Totals values={totals} label="各币种汇总" raw={rawTotals} />}
    {committed && totals.length > 0 && <Totals values={totals} label="操作后累计支出" raw={rawTotals} />}
    {query && summary.count !== 0 && categoryGroups.map(([currency, group]) => currencyCode(currency) && <div key={currency} className="fdr-expense-category">
      <h4>{currency} · 按类别</h4>
      <Items label={`${currency} 分类明细`} items={Object.entries(asRecord(group)).map(([category, amount]) => ({ category, amount, currency }))} />
    </div>)}
    {query && recent.length > 0 && <div className="fdr-expense-category"><h4>最近明细</h4><Items items={recent} label="最近费用" /></div>}
    {answer && <p className="fdr-summary whitespace-pre-wrap" data-error={failed || undefined}>{answer}</p>}
    {!answer && query && summary.count === 0 && <p className="fdr-empty">暂无费用记录。</p>}
    {!answer && query && summary.count !== 0 && !totals.length && !recent.length && <p className="fdr-empty">未返回可核对的费用金额。</p>}
    {pending && onConfirm && <div className="fdr-expense-actions">
      <span>仅在你主动确认后提交。</span>
      <button type="button" onClick={onConfirm}>确认这项费用操作</button>
    </div>}
  </FlightResult>
}
