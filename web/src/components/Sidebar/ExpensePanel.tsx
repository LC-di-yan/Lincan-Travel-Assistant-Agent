import { useState, useEffect, useCallback } from 'react'
import { RefreshCw } from 'lucide-react'
import { fetchExpenses } from '../../api/client'
import { useChatStore } from '../../store/chatStore'
import { ExpenseCategoryIcon } from '../Icons'
import { originalAmount } from '../../utils/expenseEvidence'
import { AnimatedNumber } from '../effects/AnimatedNumber'

interface ExpenseItem {
  id?: string
  category?: string
  amount?: number
  description?: string
  date?: string
  currency?: string
}

export function ExpensePanel({ personalAvailable = false }: { personalAvailable?: boolean }) {
  const userId = useChatStore((s) => s.userId)
  const sessionId = useChatStore((s) => s.sessionId)
  const [expenses, setExpenses] = useState<ExpenseItem[]>([])
  const [meta, setMeta] = useState<{ totals: Record<string, number>; count: number }>({ totals: {}, count: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [updated, setUpdated] = useState('')

  const load = useCallback(() => fetchExpenses(userId, sessionId)
    .then((data) => {
      const list = (data.expenses || []) as ExpenseItem[]
      setExpenses(list)
      setError(false)
      setUpdated(new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }))
      setMeta({
        totals: data.totals_by_currency || {},
        count: typeof data.count === 'number' ? data.count : list.length,
      })
    })
    .catch(() => setError(true))
    .finally(() => setLoading(false)), [userId, sessionId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const handler = () => { load() }
    window.addEventListener('expense-updated', handler)
    return () => window.removeEventListener('expense-updated', handler)
  }, [load])

  const count = meta.count > 0 ? meta.count : expenses.length

  return (
    <div className="p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="font-mono text-[9px] tracking-[0.16em] text-accent">ALIGO / EXPENSES</div>
          <h4 className="mt-1 text-[13px] font-semibold text-ink">费用记录</h4>
        </div>
        <button
          type="button"
          onClick={() => { setLoading(true); void load() }}
          disabled={loading}
          aria-label="刷新费用"
          title="刷新费用"
          className="flex size-11 items-center justify-center rounded-input text-ink-3 hover:bg-paper-sunken hover:text-ink"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
        </button>
      </div>
      {personalAvailable && <a href="#/personal/expenses" className="inline-flex min-h-11 items-center text-xs font-semibold text-route underline">查看完整账本</a>}
      {error && <p role="alert" className="mb-2 text-xs text-err">账本读取失败。{updated ? '屏幕上仅保留上次结果。' : '不能据此判断没有费用。'}</p>}
      {updated && <p className="text-xs text-ink-3">上次读取：{updated}（北京时间）</p>}

      <div className="border-y border-rule py-3">
        {loading && expenses.length === 0 ? (
          <>
            <div className="skeleton mx-auto mb-1.5 h-6 w-28" />
            <div className="skeleton mx-auto h-3 w-16" />
          </>
        ) : updated ? (
          <>
            {Object.entries(meta.totals).map(([currency, total]) => <div key={currency} className="break-words font-mono text-[20px] font-semibold tabular text-route">
              {Number.isFinite(Number(total)) && currency
                ? <>{currency} <AnimatedNumber value={Number(total)} precision={2} className="min-w-0" /></>
                : originalAmount(total, currency)}
            </div>)}
            {Object.keys(meta.totals).length === 0 && count > 0 && <p className="text-xs text-ink-3">未返回按币种汇总。</p>}
            {Object.keys(meta.totals).length > 1 && <p className="text-[10px] text-ink-3">按原币种分别汇总，未换算汇率</p>}
            <div className="mt-1 text-[10px] text-ink-3">{count} 笔支出</div>
          </>
        ) : null}
      </div>

      {loading && expenses.length === 0 ? (
        <div className="space-y-3 pt-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i}>
              <div className="skeleton mb-1.5 h-3 w-24" />
              <div className="skeleton h-3 w-16" />
            </div>
          ))}
        </div>
      ) : expenses.length === 0 ? (!error &&
        <div className="py-8 text-center">
          <p className="text-[12px] text-ink-2">暂无费用记录</p>
          <p className="mt-1 text-[10px] text-ink-3">在对话里说「记一笔打车费 50」试试</p>
        </div>
      ) : (
        <div>
          {expenses.slice(0, 20).map((item, i) => (
            <div key={item.id || i} className="flex items-center gap-2 border-b border-rule py-2 text-[11px] last:border-0">
              <ExpenseCategoryIcon kind={item.category} size={12} className="w-4 shrink-0 text-ink-3" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-ink-2">{item.description || item.category}</div>
                {item.date && <div className="font-mono text-[9px] text-ink-3">{item.date}</div>}
                {item.id && <div className="select-all break-all font-mono text-[9px] text-ink-3" title="费用编号">编号：{item.id}</div>}
              </div>
              <span className="font-mono tabular text-ink">{originalAmount(item.amount, item.currency)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
