import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'
import { Receipt, TrendingUp, Trash2 } from 'lucide-react'

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
  category?: string
  amount?: number
  description?: string
  date?: string
}

interface Summary {
  total?: number
  count?: number
  by_category?: Record<string, number>
  items?: ExpenseItem[]
}

function RecordView({ expense, totalAfter, answer }: { expense?: ExpenseItem; totalAfter?: number; answer?: string }) {
  if (!expense) return <p className="text-sm">{answer}</p>
  const icon = CATEGORY_ICONS[expense.category || ''] || '📦'
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
        <span className="text-2xl">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium">{expense.category || '其他'}</div>
          <div className="text-xs text-[var(--text-muted)] truncate">{expense.description || ''}</div>
        </div>
        <div className="text-right">
          <div className="text-lg font-bold text-gradient">{'¥'}{(expense.amount || 0).toFixed(2)}</div>
          {expense.date && <div className="text-xs text-[var(--text-muted)]">{expense.date}</div>}
        </div>
      </div>
      {totalAfter != null && (
        <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
          <TrendingUp size={12} />
          <span>累计 {'¥'}{totalAfter.toFixed(2)}</span>
        </div>
      )}
      {answer && <p className="text-xs text-[var(--text-secondary)]">{answer}</p>}
    </div>
  )
}

function QueryView({ summary, answer }: { summary?: Summary; answer?: string }) {
  if (!summary || summary.count === 0) {
    return (
      <div className="text-center py-4">
        <Receipt size={32} className="mx-auto mb-2 text-[var(--text-muted)] opacity-40" />
        <p className="text-xs text-[var(--text-muted)]">{answer || '暂无费用记录'}</p>
      </div>
    )
  }

  const categories = Object.entries(summary.by_category || {}).sort(([, a], [, b]) => b - a)

  return (
    <div className="space-y-3">
      {/* Total hero */}
      <div className="text-center p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
        <div className="text-2xl font-bold text-gradient">{'¥'}{(summary.total || 0).toFixed(2)}</div>
        <div className="text-xs text-[var(--text-muted)] mt-1">{summary.count} 笔支出</div>
      </div>

      {/* Category breakdown */}
      {categories.length > 0 && (
        <div className="space-y-1.5">
          {categories.map(([cat, amt]) => {
            const pct = summary.total ? Math.round((amt / summary.total) * 100) : 0
            return (
              <div key={cat} className="flex items-center gap-2 text-xs">
                <span className="w-5 text-center">{CATEGORY_ICONS[cat] || '📦'}</span>
                <span className="flex-1 truncate">{cat}</span>
                <div className="w-20 h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: 'var(--accent)' }} />
                </div>
                <span className="w-16 text-right font-medium">{'¥'}{amt.toFixed(0)}</span>
              </div>
            )
          })}
        </div>
      )}

      {/* Recent items */}
      {summary.items && summary.items.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-[var(--text-muted)] font-medium">最近记录</div>
          {summary.items.slice(-5).reverse().map((item, i) => (
            <div key={i} className="flex items-center gap-2 text-xs p-1.5 rounded-lg"
              style={{ backgroundColor: 'var(--bg-secondary)' }}>
              <span>{CATEGORY_ICONS[item.category || ''] || '📦'}</span>
              <span className="flex-1 truncate">{item.description || item.category}</span>
              <span className="font-medium">{'¥'}{(item.amount || 0).toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}

      {answer && <p className="text-xs text-[var(--text-secondary)]">{answer}</p>}
    </div>
  )
}

function DeleteView({ answer, deletedId }: { answer?: string; deletedId?: string }) {
  return (
    <div className="flex items-center gap-2 p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
      <Trash2 size={16} className="text-[var(--error)]" />
      <div>
        <p className="text-sm">{answer || '已删除费用记录'}</p>
        {deletedId && <p className="text-xs text-[var(--text-muted)]">ID: {deletedId}</p>}
      </div>
    </div>
  )
}

export function ExpenseCard({ data }: { data: Record<string, unknown> }) {
  const action = data.action as string

  return (
    <CardShell agentName="expense_tracker">
      <div className="p-4 space-y-2">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="expense_tracker" size={16} />
          {action === 'record' ? '费用已记录' : action === 'delete' ? '费用已删除' : '费用汇总'}
        </h4>

        {action === 'record' && (
          <RecordView
            expense={data.expense as ExpenseItem | undefined}
            totalAfter={data.total_after as number | undefined}
            answer={data.answer as string | undefined}
          />
        )}
        {action === 'query' && (
          <QueryView
            summary={data.summary as Summary | undefined}
            answer={data.answer as string | undefined}
          />
        )}
        {action === 'delete' && (
          <DeleteView
            answer={data.answer as string | undefined}
            deletedId={data.deleted_id as string | undefined}
          />
        )}
        {action === 'error' && (
          <p className="text-sm text-[var(--error)]">{String(data.answer || '操作失败')}</p>
        )}
        {!['record', 'query', 'delete', 'error'].includes(action || '') && (
          <p className="text-sm">{String(data.answer || JSON.stringify(data))}</p>
        )}
      </div>
    </CardShell>
  )
}
