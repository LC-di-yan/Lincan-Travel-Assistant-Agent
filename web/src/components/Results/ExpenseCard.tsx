import { asRecord } from '../../utils/resultData'
import { currencyCode, expenseTotals, originalAmount } from '../../utils/expenseEvidence'
import { evidenceSources, evidenceText } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult } from './FlightResult'

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

function Totals({ values, label }: { values: ReturnType<typeof expenseTotals>; label: string }) {
  return <div className="fdr-expense-totals">
    <h4>{label} <small>保留原币，不换算</small></h4>
    <ul>{values.map(({ display }, index) => <li key={index}>
      <strong>{display}</strong>
    </li>)}</ul>
  </div>
}

export function ExpenseCard({ data, onConfirm, fresh = false, submitting = false }: {
  data: Record<string, unknown>; onConfirm?: () => void; fresh?: boolean; submitting?: boolean
}) {
  const action = data.action
  const answer = evidenceText(data.answer)
  const summary = asRecord(data.summary)
  const expense = asRecord(data.expense)
  const items = records(data.expenses)
  const lines = items.length ? items : Object.keys(expense).length ? [expense] : []
  const pending = action === 'preview'
  const failed = action === 'error' || action === 'unknown'
  const committed = action === 'record' || action === 'update' || action === 'delete'
  const query = !pending && !committed && !failed
  const fallbackSource = pending ? '当前会话的操作预览' : failed ? '本次账本操作提示' : '当前费用账本'
  const sources = evidenceSources([{ title: fallbackSource }], data.sources, summary.sources)
  const operation = data.operation === 'update' ? '修改费用' : data.operation === 'delete' ? '删除费用' : '新增费用'
  const title = pending ? operation : action === 'delete' ? '费用已删除' : action === 'update' ? '费用已修改'
    : action === 'record' ? '费用已记录' : failed ? '费用操作未确认成功' : '费用汇总'
  const totals = query ? expenseTotals(summary.totals_by_currency, { amount: summary.total, currency: summary.currency })
    : expenseTotals(data.totals_by_currency, { amount: data.total_after, currency: data.total_currency ?? expense.currency })
  const categories = asRecord(summary.by_category_by_currency)
  const onlyCurrency = totals.length === 1 ? totals[0].currency : ''
  const flat = asRecord(summary.by_category)
  const categoryGroups = Object.keys(categories).length ? Object.entries(categories)
    : Object.keys(flat).length && onlyCurrency && currencyCode(summary.currency) === onlyCurrency ? [[onlyCurrency, flat] as const] : []
  const recent = records(summary.items).slice(-5).reverse()

  return <FlightResult agent="expense_tracker" kind="费用回执" title={title}
    meta={query && typeof summary.count === 'number' ? <span>{summary.count} 笔</span> : undefined}>
    <EvidenceBand
      label={pending ? '预览' : committed ? '已确认' : failed ? '未确认' : '账本查询'}
      status={pending ? submitting ? '已提交确认 · 等待账本回执' : onConfirm ? '待确认 · 账本未修改' : '预览快照 · 当时未写入'
        : committed ? '账本已更新' : failed ? '未收到成功回执' : '按原币分别显示'}
      sources={sources} tone={committed ? 'confirmed' : pending || failed ? 'warning' : 'neutral'}
      live={submitting || fresh && committed} stamp={fresh && committed}>
      {pending && !onConfirm && !submitting && <p>当前不能在此确认，请以最新回执为准。</p>}
    </EvidenceBand>
    {lines.length > 0 && !query && !failed && <Items items={lines} label={pending && operation !== '新增费用' ? '原账本记录' : '费用原币明细'} />}
    {query && summary.count !== 0 && totals.length > 0 && <Totals values={totals} label="各币种汇总" />}
    {committed && totals.length > 0 && <Totals values={totals} label="操作后累计支出" />}
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
