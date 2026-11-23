import { EvidenceBand, FlightResult } from './FlightResult'
import { evidenceSources, evidenceText } from '../../utils/flightEvidence'

export function EventCard({ data }: { data: Record<string, unknown> }) {
  const origin = evidenceText(data.origin)
  const destination = evidenceText(data.destination)
  const dates = [evidenceText(data.start_date), evidenceText(data.end_date)].filter(Boolean).join(' 至 ')
  const purpose = evidenceText(data.trip_purpose)
  const summary = evidenceText(data.summary)
  const missing = Array.isArray(data.missing_info) ? data.missing_info.map(evidenceText).filter(Boolean) : []
  return <FlightResult agent="event_collection" kind="事项简报" title={destination ? `前往${destination}` : '核对差旅事项'}>
    <EvidenceBand label={missing.length ? '待补充' : '本轮资料'} tone={missing.length ? 'warning' : 'neutral'}
      status={missing.length ? '缺少信息：' + missing.join('、') : '事项简报不代表已安排'} sources={evidenceSources(data.sources)} />
    <dl className="fdr-receipt-pair">
      <div><dt>出发地</dt><dd>{origin || '待补充'}</dd></div>
      <div><dt>目的地</dt><dd>{destination || '待补充'}</dd></div>
    </dl>
    {(dates || purpose || summary) && <div className="fdr-summary whitespace-pre-wrap">
      {dates && <p>日期：{dates}</p>}{purpose && <p>事由：{purpose}</p>}{summary && <p>{summary}</p>}
    </div>}
  </FlightResult>
}
