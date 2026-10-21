import { useState, useEffect, useCallback } from 'react'
import { RefreshCw } from 'lucide-react'
import { fetchExpenses } from '../../api/client'
import { useChatStore } from '../../store/chatStore'

const CATEGORY_ICONS: Record<string, string> = {
  '交通': '🚕',
  '餐饮': '🍽️',
  '住宿': '🏨',
  '通讯': '📱',
  '办公': '💼',
  '娱乐': '🎬',
  '其他': '📦',
}

interface ExpenseItem {
  id?: string
  category?: string
  amount?: number
  description?: string
  date?: string
}

export function ExpensePanel() {
  const userId = useChatStore((s) => s.userId)
  const sessionId = useChatStore((s) => s.sessionId)
  const [expenses, setExpenses] = useState<ExpenseItem[]>([])
  const [meta, setMeta] = useState({ total: 0, count: 0 })
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchExpenses(userId, sessionId)
      const list = (data.expenses || []) as ExpenseItem[]
      setExpenses(list)
      setMeta({
        total: typeof data.total === 'number' ? data.total : list.reduce((s, e) => s + (e.amount || 0), 0),
        count: typeof data.count === 'number' ? data.count : list.length,
      })
    } catch {
      /* keep last state */
    }
    setLoading(false)
  }, [userId, sessionId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const handler = () => { load() }
    window.addEventListener('expense-updated', handler)
    return () => window.removeEventListener('expense-updated', handler)
  }, [load])

  const listTotal = expenses.reduce((sum, e) => sum + (e.amount || 0), 0)
  const total = meta.count > 0 ? meta.total : listTotal
  const count = meta.count > 0 ? meta.count : expenses.length
  const byCategory: Record<string, number> = {}
  for (const e of expenses) {
    const cat = e.category || '其他'
    byCategory[cat] = (byCategory[cat] || 0) + (e.amount || 0)
  }
  const categories = Object.entries(byCategory).sort(([, a], [, b]) => b - a)

  return (
    <div className="p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="font-mono text-[9px] tracking-[0.16em] text-accent">ALIGO / EXPENSES</div>
          <h4 className="mt-1 text-[13px] font-semibold text-ink">费用记录</h4>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          aria-label="刷新费用"
          title="刷新费用"
          className="flex h-10 w-10 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
        </button>
      </div>

      <div className="border-y border-rule py-3">
        {loading && expenses.length === 0 ? (
          <>
            <div className="skeleton mx-auto mb-1.5 h-6 w-28" />
            <div className="skeleton mx-auto h-3 w-16" />
          </>
        ) : (
          <>
            <div className="font-mono text-[24px] font-semibold tabular text-accent">{'¥'}{total.toFixed(2)}</div>
            <div className="mt-1 text-[10px] text-ink-3">{count} 笔支出</div>
          </>
        )}
      </div>

      {categories.length > 0 && (
        <div className="border-b border-rule py-3">
          <div className="mb-2 font-mono text-[9px] tracking-[0.14em] text-ink-3">BY CATEGORY</div>
          {categories.map(([cat, amt]) => {
            const pct = total > 0 ? Math.round((amt / total) * 100) : 0
            return (
              <div key={cat} className="flex items-center gap-2 py-1 text-[11px]">
                <span className="w-4 text-center" aria-hidden="true">{CATEGORY_ICONS[cat] || '📦'}</span>
                <span className="w-10 shrink-0 text-ink-2">{cat}</span>
                <div className="h-1 flex-1 bg-paper-sunken">
                  <div className="h-full bg-accent" style={{ width: pct + '%' }} />
                </div>
                <span className="w-14 text-right font-mono tabular text-ink">{'¥'}{amt.toFixed(0)}</span>
              </div>
            )
          })}
        </div>
      )}

      {loading && expenses.length === 0 ? (
        <div className="space-y-3 pt-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i}>
              <div className="skeleton mb-1.5 h-3 w-24" />
              <div className="skeleton h-3 w-16" />
            </div>
          ))}
        </div>
      ) : expenses.length === 0 ? (
        <div className="py-8 text-center">
          <p className="text-[12px] text-ink-2">暂无费用记录</p>
          <p className="mt-1 text-[10px] text-ink-3">在对话里说「记一笔打车费 50」试试</p>
        </div>
      ) : (
        <div>
          {expenses.slice(0, 20).map((item, i) => (
            <div key={item.id || i} className="flex items-center gap-2 border-b border-rule py-2 text-[11px] last:border-0">
              <span className="w-4 text-center" aria-hidden="true">{CATEGORY_ICONS[item.category || ''] || '📦'}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-ink-2">{item.description || item.category}</div>
                {item.date && <div className="font-mono text-[9px] text-ink-3">{item.date}</div>}
              </div>
              <span className="whitespace-nowrap font-mono tabular text-ink">{'¥'}{(item.amount || 0).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
