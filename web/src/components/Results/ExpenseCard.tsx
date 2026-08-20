import { CardShell } from './CardShell'
import { CompactReceipt, CompactReceiptHero } from './CompactReceipt'
import { getAgentColor } from '../Icons'
import { Receipt, Trash2 } from 'lucide-react'

const CATEGORY_ICONS: Record<string, string> = {
  '交通': '\u{1F695}',
  '餐饮': '\u{1F37D}',
  '住宿': '\u{1F3E8}',
  '通讯': '\u{1F4F1}',
  '办公': '\u{1F4BC}',
  '娱乐': '\u{1F3AC}',
  '其他': '\u{1F4E6}',
}

const accent = getAgentColor('expense_tracker')

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
  const icon = CATEGORY_ICONS[expense.category || ''] || '\u{1F4E6}'
  const label = expense.description
    ? `${expense.category || '其他'} - ${expense.description}`
    : (expense.category || '其他')

  return (
    <CompactReceipt
      accentColor={accent}
      badge="✓ 已记录"
      footer={totalAfter != null ? '\u{1F4B0} 累计报销' : undefined}
      footerSecondary={totalAfter != null ? `¥ ${totalAfter.toFixed(2)}` : undefined}
    >
      <CompactReceiptHero
        emoji={icon}
        label={label}
        value={`¥ ${(expense.amount || 0).toFixed(2)}`}
        accentColor={accent}
      />
    </CompactReceipt>
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
      <div className="text-center p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
        <div className="text-2xl font-bold text-gradient">{'¥'}{(summary.total || 0).toFixed(2)}</div>
        <div className="text-xs text-[var(--text-muted)] mt-1">{summary.count} 笔支出</div>
      </div>
      {categories.length > 0 && (
        <div className="space-y-1.5">
          {categories.map(([cat, amt]) => {
            const pct = summary.total ? Math.round((amt / summary.total) * 100) : 0
            return (
              <div key={cat} className="flex items-center gap-2 text-xs">
                <span className="w-5 text-center">{CATEGORY_ICONS[cat] || '\u{1F4E6}'}</span>
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
      {summary.items && summary.items.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-[var(--text-muted)] font-medium">最近记录</div>
          {summary.items.slice(-5).reverse().map((item, i) => (
            <div key={i} className="flex items-center gap-2 text-xs p-1.5 rounded-lg"
              style={{ backgroundColor: 'var(--bg-secondary)' }}>
              <span>{CATEGORY_ICONS[item.category || ''] || '\u{1F4E6}'}</span>
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

function DeleteView({ answer }: { answer?: string }) {
  return (
    <CompactReceipt accentColor="#ef4444" badge="✓ 已删除">
      <div className="flex items-center gap-2 py-1">
        <Trash2 size={16} className="text-[var(--error)]" />
        <p className="text-sm">{answer || '已删除费用记录'}</p>
      </div>
    </CompactReceipt>
  )
}

export function ExpenseCard({ data }: { data: Record<string, unknown> }) {
  const action = data.action as string

  if (action === 'record') {
    return (
      <RecordView
        expense={data.expense as ExpenseItem | undefined}
        totalAfter={data.total_after as number | undefined}
        answer={data.answer as string | undefined}
      />
    )
  }

  if (action === 'delete') {
    return (
      <DeleteView
        answer={data.answer as string | undefined}
      />
    )
  }

  // query / default → keep CardShell for complex summary
  return (
    <CardShell agentName="expense_tracker">
      <div className="p-4 space-y-2">
        <QueryView
          summary={data.summary as Summary | undefined}
          answer={data.answer as string | undefined}
        />
      </div>
    </CardShell>
  )
}
