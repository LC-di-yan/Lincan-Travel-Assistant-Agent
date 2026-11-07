import { CompactReceipt, CompactReceiptExchange } from './CompactReceipt'
import { getAgentColor } from '../Icons'

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
      <CompactReceipt accentColor="var(--err)" eyebrow="ALIGO / FX" title="汇率换算">
        <p className="py-2 text-center text-sm text-err">{answer || '查询失败'}</p>
      </CompactReceipt>
    )
  }

  return (
    <CompactReceipt
      accentColor={accent}
      eyebrow="ALIGO / FX"
      title="汇率换算"
      footer={rate ? '1 ' + from + ' = ' + rate + ' ' + to : undefined}
    >
      <CompactReceiptExchange
        from={{ code: from, value: amount + ' ' + from, mono: true }}
        to={{ code: to, value: result.toFixed(2) + ' ' + to, mono: true }}
      />
    </CompactReceipt>
  )
}
