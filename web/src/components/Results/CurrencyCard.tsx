import { CompactReceipt, CompactReceiptExchange } from './CompactReceipt'
import { getAgentColor } from '../Icons'

const FLAGS: Record<string, string> = {
  CNY: '\u{1F1E8}\u{1F1F3}', USD: '\u{1F1FA}\u{1F1F8}', EUR: '\u{1F1EA}\u{1F1FA}',
  GBP: '\u{1F1EC}\u{1F1E7}', JPY: '\u{1F1EF}\u{1F1F5}', KRW: '\u{1F1F0}\u{1F1F7}',
  HKD: '\u{1F1ED}\u{1F1F0}', TWD: '\u{1F1F9}\u{1F1FC}', SGD: '\u{1F1F8}\u{1F1EC}',
  THB: '\u{1F1F9}\u{1F1ED}', AUD: '\u{1F1E6}\u{1F1FA}', CAD: '\u{1F1E8}\u{1F1E6}',
}

const accent = getAgentColor('currency_converter')

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
      <CompactReceipt accentColor="#ef4444">
        <p className="text-sm text-center text-[var(--error)] py-2">{answer || '查询失败'}</p>
      </CompactReceipt>
    )
  }

  return (
    <CompactReceipt
      accentColor={accent}
      footer={rate ? `\u{1F4CA} 1 ${from} = ${rate} ${to}` : undefined}
    >
      <CompactReceiptExchange
        from={{
          icon: FLAGS[from] || '\u{1F4B1}',
          value: `${amount} ${from}`,
        }}
        to={{
          icon: FLAGS[to] || '\u{1F4B1}',
          value: `${result.toFixed(2)} ${to}`,
        }}
      />
    </CompactReceipt>
  )
}
