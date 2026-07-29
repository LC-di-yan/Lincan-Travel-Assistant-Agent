import { useState, useEffect, useCallback } from 'react'
import { Receipt, RefreshCw, TrendingUp } from 'lucide-react'
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
  const [expenses, setExpenses] = useState<ExpenseItem[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchExpenses(userId)
      setExpenses(data.expenses || [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [userId])

  useEffect(() => { load() }, [load])

  // 费用记录更新时自动刷新
  useEffect(() => {
    const handler = () => { load() }
    window.addEventListener('expense-updated', handler)
    return () => window.removeEventListener('expense-updated', handler)
  }, [load])

  const total = expenses.reduce((sum, e) => sum + (e.amount || 0), 0)

  const byCategory: Record<string, number> = {}
  for (const e of expenses) {
    const cat = e.category || '其他'
    byCategory[cat] = (byCategory[cat] || 0) + (e.amount || 0)
  }
  const categories = Object.entries(byCategory).sort(([, a], [, b]) => b - a)

  return (
    <div className="p-3">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold text-[var(--text-muted)] flex items-center gap-1">
          <Receipt size={10} /> 费用记录
        </h4>
        <button onClick={load} disabled={loading}
          className="p-1.5 rounded-lg transition-all hover:bg-[var(--bg-tertiary)] hover:scale-105 active:scale-95">
          <RefreshCw size={12} className={`text-[var(--text-muted)] ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Total */}
      <div className="p-3 rounded-xl text-center mb-3" style={{ backgroundColor: 'var(--bg-secondary)' }}>
        {loading ? (
          <>
            <div className="skeleton h-7 w-24 mx-auto mb-1.5" />
            <div className="skeleton h-3 w-16 mx-auto" />
          </>
        ) : (
          <>
            <div className="text-2xl font-bold text-gradient">{'¥'}{total.toFixed(2)}</div>
            <div className="text-xs text-[var(--text-muted)] mt-1">{expenses.length} 笔支出</div>
          </>
        )}
      </div>

      {/* Category breakdown */}
      {categories.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs text-[var(--text-muted)] mb-2 flex items-center gap-1">
            <TrendingUp size={10} /> 分类统计
          </h5>
          <div className="space-y-1.5">
            {categories.map(([cat, amt]) => {
              const pct = total > 0 ? Math.round((amt / total) * 100) : 0
              return (
                <div key={cat} className="flex items-center gap-2 text-xs">
                  <span className="w-5 text-center">{CATEGORY_ICONS[cat] || '📦'}</span>
                  <span className="flex-1 truncate">{cat}</span>
                  <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: 'var(--accent)' }} />
                  </div>
                  <span className="w-14 text-right font-medium">{'¥'}{amt.toFixed(0)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Expense list */}
      {loading && expenses.length === 0 ? (
        <div className="space-y-1.5">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2 p-2 rounded-lg"
              style={{ backgroundColor: 'var(--bg-secondary)' }}>
              <div className="skeleton w-5 h-5 rounded" />
              <div className="flex-1">
                <div className="skeleton h-3 w-20 mb-1" />
                <div className="skeleton h-2.5 w-16" />
              </div>
              <div className="skeleton h-3 w-12" />
            </div>
          ))}
        </div>
      ) : expenses.length === 0 ? (
        <div className="text-center py-6">
          <Receipt size={32} className="mx-auto mb-2 text-[var(--text-muted)] opacity-40" />
          <p className="text-xs text-[var(--text-muted)]">暂无费用记录</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">对话中说"记一笔打车费50"试试</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {expenses.slice().reverse().slice(0, 20).map((item, i) => (
            <div key={item.id || i} className="flex items-center gap-2 text-xs p-2 rounded-lg transition-all card-hover"
              style={{ backgroundColor: 'var(--bg-secondary)' }}>
              <span className="w-5 text-center">{CATEGORY_ICONS[item.category || ''] || '📦'}</span>
              <div className="flex-1 min-w-0">
                <div className="truncate">{item.description || item.category}</div>
                {item.date && <div className="text-[10px] text-[var(--text-muted)]">{item.date}</div>}
              </div>
              <span className="font-medium whitespace-nowrap">{'¥'}{(item.amount || 0).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
