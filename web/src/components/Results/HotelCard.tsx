import { useId, useState } from 'react'
import { MapPin } from 'lucide-react'
import { asRecord } from '../../utils/resultData'
import { amapMarker, beijingQueryTime, evidenceSources, evidenceText, mapReference } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult, ResultDisclosure } from './FlightResult'

const SHOW = 5

export function HotelCard({ data }: { data: Record<string, unknown> }) {
  const results = asRecord(data.results ?? data)
  const hotels = Array.isArray(results.hotels) ? results.hotels.map(asRecord) : []
  const city = evidenceText(results.city)
  const keyword = evidenceText(results.keyword) || '酒店'
  const title = city && !keyword.startsWith(city) ? `${city} · ${keyword}` : keyword
  const summary = evidenceText(results.summary)
  const error = evidenceText(data.error)
  const budgetStatus = evidenceText(results.budget_status)
  const timestamp = evidenceText(results.queried_at)
  const beijing = beijingQueryTime(timestamp)
  const total = typeof results.count === 'number' && results.count > 0 ? results.count : hotels.length
  const sources = evidenceSources(results.sources, data.sources)
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  const shown = expanded ? hotels : hotels.slice(0, SHOW)

  return <FlightResult agent="hotel_search" kind="住宿候选" title={title}
    meta={total > 0 ? <span>{total >= 600 ? '共 600+ 家' : `共 ${total} 家`}</span> : undefined}>
    <EvidenceBand label="待核验" status="指定日期的房价与房态未核验" sources={sources}>
      <p>地图价格仅供参考，不是可订报价，也不代表含税实付。</p>
      {(beijing || timestamp) && <p>{beijing ? `查询时间 ${beijing}（北京时间）` : `查询时间原文：${timestamp}`}</p>}
    </EvidenceBand>
    {summary && <p className="fdr-summary">{summary}</p>}
    {error && error !== summary && <p className="fdr-summary text-err">{error}</p>}
    {!hotels.length && !summary && !error && <p className="fdr-empty">{budgetStatus
      ? '未将缺价或超预算的条目计入推荐' : '未找到相关住宿信息，请尝试更换城市或关键词'}</p>}
    {hotels.length > 0 && <div className="fdr-section-head">
      <h4>住宿清单 <small>显示 {shown.length} / {hotels.length} 家</small></h4>
      {hotels.length > SHOW && <ResultDisclosure controls={listId} open={expanded}
        onToggle={() => setExpanded(!expanded)}>{expanded ? '收起住宿' : `查看全部 ${hotels.length} 家`}</ResultDisclosure>}
    </div>}
    <ol id={listId} className="fdr-hotels">{shown.map((hotel, index) => {
      const name = evidenceText(hotel.name) || '住宿名称未提供'
      const address = evidenceText(hotel.address)
      const link = amapMarker(hotel.location, name)
      const rating = Number(hotel.rating)
      const distance = Number(hotel.distance)
      const price = mapReference(hotel.cost)
      return <li key={index} className="fdr-hotel">
        <span className="fdr-day-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <div className="fdr-hotel-name">
          <h5>{name}</h5>
          <p>{address || '地址未提供'}</p>
          <p className="fdr-hotel-meta">
            {Number.isFinite(rating) && rating > 0 && <span>评分 {String(hotel.rating)}</span>}
            {Number.isFinite(distance) && distance > 0 && <span>距搜索点 {distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${Math.round(distance)} m`}</span>}
          </p>
          {link && <a href={link} target="_blank" rel="noopener noreferrer" className="fdr-inline-link" aria-label={`在高德打开：${name}`}>
            <MapPin size={14} aria-hidden="true" />在高德打开
          </a>}
        </div>
        <div className="fdr-hotel-price" data-unknown={price.kind !== 'reference' || undefined}>
          <strong>{price.kind === 'reference' ? <>参考 <span className="fdr-price-number">{price.raw}</span></> : '房价待核验'}</strong>
          <small>{price.kind === 'reference' ? '地图参考价' : price.kind === 'unclear' ? `来源原文：${price.raw}` : '未提供可用参考价'}</small>
        </div>
      </li>
    })}</ol>
  </FlightResult>
}
