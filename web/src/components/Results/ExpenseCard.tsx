import { CardShell } from './CardShell'
import { CompactReceipt, CompactReceiptHero } from './CompactReceipt'
import { getAgentColor } from '../Icons'
import { Receipt, Trash2 } from 'lucide-react'

const CATEGORY_ICONS: Record<string, string> = {
  '交通': '🚕',
  '餐饮': '🍽️',
  '住宿': '🏨',
  '通讯': '📱',
  '办公': '💼',
  '娱乐': '🎬',
  '其他': '📦',
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
  if (!expense) {
    return (
      <CompactReceipt accentColor={accent} eyebrow="ALIGO / EXPENSE" title="费用记录" badge="已记录">
        <p className="py-2 text-center text-[13px] text-ink-2">{answer || '费用已记录'}</p>
      </CompactReceipt>
    )
  }

  const icon = CATEGORY_ICONS[expense.category || ''] || '📦'
  const label = expense.description
    ? (expense.category || '其他') + ' · ' + expense.description
    : (expense.category || '其他')

  return (
    <CompactReceipt
      accentColor={accent}
      eyebrow="ALIGO / EXPENSE"
      title="费用已记录"
      badge="✓ 已记录"
      footer={totalAfter != null ? '累计报销' : undefined}
      footerSecondary={totalAfter != null ? '¥ ' + totalAfter.toFixed(2) : undefined}
    >
      <CompactReceiptHero
        emoji={icon}
        label={label}
        value={'¥ ' + (expense.amount || 0).toFixed(2)}
        accentColor={accent}
      />
    </CompactReceipt>
  )
}

function QueryView({ summary, answer }: { summary?: Summary; answer?: string }) {
  if (!summary || summary.count === 0) {
    return (
      <div className="py-6 text-center">
        <Receipt size={28} className="mx-auto mb-2 text-ink-3 opacity-50" aria-hidden="true" />
        <p className="text-[12px] text-ink-3">{answer || '暂无费用记录'}</p>
      </div>
    )
  }

  const categories = Object.entries(summary.by_category || {}).sort(([, a], [, b]) => b - a)

  return (
    <div>
      <div className="flex items-baseline justify-between border-b border-rule pb-2">
        <span className="font-mono text-[26px] font-semibold tabular text-accent">
          {'¥'}{(summary.total || 0).toFixed(2)}
        </span>
        <span className="text-[11px] text-ink-3">{summary.count} 笔支出</span>
      </div>

      {categories.length > 0 && (
        <div className="border-b border-rule py-2">
          {categories.map(([cat, amt]) => {
            const pct = summary.total ? Math.round((amt / summary.total) * 100) : 0
            return (
              <div key={cat} className="flex items-center gap-2 py-1 text-[11px]">
                <span className="w-4 text-center" aria-hidden="true">{CATEGORY_ICONS[cat] || '📦'}</span>
                <span className="w-10 shrink-0 text-ink-2">{cat}</span>
                <div className="h-1 flex-1 overflow-hidden bg-paper-sunken">
                  <div className="h-full bg-accent" style={{ width: pct + '%' }} />
                </div>
                <span className="w-14 text-right font-mono tabular text-ink">{'¥'}{amt.toFixed(0)}</span>
              </div>
            )
          })}
        </div>
      )}

      {summary.items && summary.items.length > 0 && (
        <div>
          <div className="pt-2 font-mono text-[9px] tracking-[0.12em] text-ink-3">RECENT</div>
          {summary.items.slice(-5).reverse().map((item, i) => (
            <div key={i} className="flex items-center gap-2 border-b border-rule py-1.5 text-[11px] last:border-0">
              <span aria-hidden="true">{CATEGORY_ICONS[item.category || ''] || '📦'}</span>
              <span className="flex-1 truncate text-ink-2">{item.description || item.category}</span>
              <span className="font-mono tabular text-ink">{'¥'}{(item.amount || 0).toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}

      {answer && <p className="mt-2 text-[11px] leading-5 text-ink-3">{answer}</p>}
    </div>
  )
}

function DeleteView({ answer }: { answer?: string }) {
  return (
    <CompactReceipt accentColor="var(--err)" eyebrow="ALIGO / EXPENSE" title="费用已删除" badge="✓">
      <div className="flex items-center gap-2 py-1">
        <Trash2 size={14} className="text-err" aria-hidden="true" />
        <p className="text-[13px] text-ink-2">{answer || '已删除费用记录'}</p>
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
    return <DeleteView answer={data.answer as string | undefined} />
  }

  return (
    <CardShell agentName="expense_tracker">
      <div className="border-b border-rule px-4 py-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / EXPENSE</div>
        <h4 className="mt-1 text-[15px] font-semibold text-ink">费用汇总</h4>
      </div>
      <div className="px-4 py-3">
        <QueryView
          summary={data.summary as Summary | undefined}
          answer={data.answer as string | undefined}
        />
      </div>
    </CardShell>
  )
}
