import { useId, useState } from 'react'
import { asRecord } from '../../utils/resultData'
import { activityTime, beijingQueryTime, evidenceSources, evidenceText, seatStatus } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult, ResultDisclosure } from './FlightResult'

const RAIL = 'https://www.12306.cn/'
const SHOW = 3
const seats = [
  ['second_class', '二等座'], ['first_class', '一等座'], ['business', '商务座'],
  ['hard_sleeper', '硬卧'], ['soft_sleeper', '软卧'], ['hard_seat', '硬座'], ['no_seat', '无座'],
] as const

export function TrainCard({ data }: { data: Record<string, unknown> }) {
  const results = asRecord(data.results ?? data)
  const unavailable = data.availability_status === 'unavailable'
  const failed = data.availability_status === 'failure' || (data.query_success === false && !unavailable)
  const partial = data.availability_status === 'partial'
  const isAvailability = Array.isArray(results.trains) && !unavailable && !failed
  const trains = isAvailability ? (results.trains as unknown[]).map(asRecord) : []
  const from = evidenceText(results.from)
  const to = evidenceText(results.to)
  const date = evidenceText(results.date)
  const total = typeof results.total === 'number' && results.total >= trains.length ? results.total : trains.length
  const summary = evidenceText(results.summary) || evidenceText(data.answer)
  const timestamp = evidenceText(results.queried_at)
  const beijing = beijingQueryTime(timestamp)
  const sources = evidenceSources(results.sources, data.sources)
  const hasRailSource = sources.some(source => /12306/i.test(source.title) || source.url?.includes('12306.cn'))
  const shownSources = isAvailability && !hasRailSource ? [...sources, { title: '铁路12306', url: RAIL }] : sources
  const expandedByRequest = Boolean(results.expanded || data.expanded)
  const [expanded, setExpanded] = useState(false)
  const id = useId()
  const shown = expanded || expandedByRequest ? trains : trains.slice(0, SHOW)

  return <FlightResult agent="train_ticket" kind="铁路车票" title={from && to ? `${from} → ${to}` : '铁路查询'}
    meta={<>{date && <span>{date}</span>}
      <span>{unavailable ? '数据暂不可用' : failed ? '查询失败' : partial ? '部分数据可用' : '铁路查询结果'}</span>
      {isAvailability && <span>{total} 趟</span>}</>}>
    <EvidenceBand label="待核验" status="官方票价未核验" sources={shownSources}>
      {isAvailability && <p>{beijing ? `查询时间 ${beijing}（北京时间）；`
        : timestamp ? `查询时间原文：${timestamp}；` : ''}席别数据并非价格或订票凭证。</p>}
      <a className="fdr-inline-link" href={RAIL} target="_blank" rel="noopener noreferrer">前往12306核验</a>
    </EvidenceBand>
    {summary && <p className="fdr-summary">{summary}</p>}
    {trains.length === 0 && !summary && <p className="fdr-empty">{isAvailability ? '本次未查到符合条件的车次。' : '暂无可核验数据。'}</p>}
    {trains.length > 0 && <div className="fdr-section-head">
      <h4>车次与席别 <small>{expandedByRequest ? '已展开结果' : `显示 ${shown.length} / ${trains.length} 趟`}</small></h4>
      {!expandedByRequest && trains.length > SHOW && <ResultDisclosure controls={id} open={expanded}
        onToggle={() => setExpanded(!expanded)}>{expanded ? '收起车次' : `展开其余 ${trains.length - SHOW} 趟`}</ResultDisclosure>}
    </div>}
    <ul className="fdr-trains" id={id}>{shown.map((train, index) => {
      const trainNo = evidenceText(train.train_no)
      return <li key={index} className="fdr-train">
        <div className="fdr-train-id"><strong>{trainNo || '车次未提供'}</strong>
          <small>{[evidenceText(train.train_type), evidenceText(train.duration)].filter(Boolean).join(' · ')}</small>
        </div>
        <div className="fdr-train-track" aria-label="出发至到达">
          <div><span>出发</span><strong>{activityTime(train.depart_time) || '时刻待核验'}</strong><small>{evidenceText(train.from_station) || '车站未提供'}</small></div>
          <i aria-hidden="true" />
          <div><span>到达</span><strong>{activityTime(train.arrive_time) || '时刻待核验'}</strong><small>{evidenceText(train.to_station) || '车站未提供'}</small></div>
        </div>
        <dl className="fdr-seats">{seats.map(([key, name], i) => {
          const value = seatStatus(train[key])
          if (i > 2 && (!value.known || value.text === '无')) return null
          return <div key={key} data-unknown={!value.known || undefined}><dt>{name}</dt><dd>{value.text}</dd></div>
        })}</dl>
      </li>
    })}</ul>
  </FlightResult>
}
