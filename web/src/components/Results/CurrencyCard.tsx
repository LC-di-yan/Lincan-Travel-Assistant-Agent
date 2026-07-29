import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'
import { ArrowRight, TrendingUp } from 'lucide-react'

const CURRENCY_FLAGS: Record<string, string> = {
  CNY: '🇨🇳', USD: '🇺🇸', EUR: '🇪🇺', GBP: '🇬🇧', JPY: '🇯🇵',
  KRW: '🇰🇷', HKD: '🇭🇰', TWD: '🇹🇼', SGD: '🇸🇬', THB: '🇹🇭',
  AUD: '🇦🇺', CAD: '🇨🇦',
}

export function CurrencyCard({ data }: { data: Record<string, unknown> }) {
  const action = data.action as string
  const from = data.from as string || ''
  const to = data.to as string || ''
  const amount = data.amount as number || 0
  const rate = data.rate as number || 0
  const result = data.result as number || 0
  const answer = data.answer as string || ''

  if (action === 'error') {
    return (
      <CardShell agentName="currency_converter">
        <div className="p-4">
          <h4 className="font-semibold text-sm flex items-center gap-1.5 mb-2">
            <AgentIcon agentName="currency_converter" size={16} />
            汇率查询
          </h4>
          <p className="text-sm text-[var(--error)]">{answer}</p>
        </div>
      </CardShell>
    )
  }

  return (
    <CardShell agentName="currency_converter">
      <div className="p-4 space-y-3">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="currency_converter" size={16} />
          汇率换算
        </h4>

        {/* Conversion display */}
        <div className="flex items-center justify-center gap-3 p-4 rounded-xl"
          style={{ backgroundColor: 'var(--bg-secondary)' }}>
          {/* From */}
          <div className="text-center">
            <div className="text-lg mb-1">{CURRENCY_FLAGS[from] || '💱'}</div>
            <div className="text-xs text-[var(--text-muted)]">{from}</div>
            <div className="text-xl font-bold mt-1">{amount}</div>
          </div>

          <ArrowRight size={20} className="text-[var(--accent)] mx-2" />

          {/* To */}
          <div className="text-center">
            <div className="text-lg mb-1">{CURRENCY_FLAGS[to] || '💱'}</div>
            <div className="text-xs text-[var(--text-muted)]">{to}</div>
            <div className="text-2xl font-bold text-gradient mt-1">{result.toFixed(2)}</div>
          </div>
        </div>

        {/* Rate info */}
        <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
          <TrendingUp size={12} />
          <span>1 {from} = {rate} {to}</span>
        </div>

        {answer && <p className="text-xs text-[var(--text-secondary)]">{answer}</p>}
      </div>
    </CardShell>
  )
}
