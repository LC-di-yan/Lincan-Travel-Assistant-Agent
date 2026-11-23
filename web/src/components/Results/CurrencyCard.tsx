import { EvidenceBand, FlightResult } from './FlightResult'
import { evidenceSources, evidenceText } from '../../utils/flightEvidence'
import { Markdown } from '../Markdown'

const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null

export function CurrencyCard({ data }: { data: Record<string, unknown> }) {
  const from = evidenceText(data.from)
  const to = evidenceText(data.to)
  const amount = number(data.amount)
  const result = number(data.result)
  const rate = number(data.rate)
  const date = evidenceText(data.rate_date)
  const answer = evidenceText(data.answer)
  const sources = evidenceSources(data.sources)
  const error = data.action === 'error' || result == null || amount == null
  return <FlightResult kind="汇率回执" agent="currency_converter" title={error ? '汇率换算未完成' : '汇率换算'}>
    <EvidenceBand label={error ? '未取得' : '参考'} status={error ? answer || '暂无可核对结果' : date ? '汇率日期 ' + date : '汇率日期未提供'}
      tone={error ? 'warning' : 'neutral'} sources={sources}>
      {!error && rate != null && rate > 0 && <p>1 {from} = {rate} {to}，非实际交易价格。</p>}
    </EvidenceBand>
    {!error && <dl className="fdr-receipt-pair">
      <div><dt>换算金额</dt><dd>{amount} {from}</dd></div>
      <div><dt>参考结果</dt><dd>{result.toFixed(2)} {to}</dd></div>
    </dl>}
    {!error && answer && <div className="markdown fdr-summary"><Markdown>{answer}</Markdown></div>}
  </FlightResult>
}
