import { useId, useState } from 'react'
import { MapPin } from 'lucide-react'
import { asRecord } from '../../utils/resultData'
import { amapMarker, amapPhoto, beijingQueryTime, evidenceSources, evidenceText } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult, ResultDisclosure } from './FlightResult'

const SHOW = 5

function HotelPhoto({ url, name }: { url: string; name: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) return null
  return <img className="fdr-hotel-photo" src={url} alt={name + '的高德地图照片'}
    width={128} height={88} loading="lazy" decoding="async" referrerPolicy="no-referrer"
    onError={() => setFailed(true)} />
}

export function HotelCard({ data }: { data: Record<string, unknown> }) {
  const results = asRecord(data.results ?? data)
  const hotels = Array.isArray(results.hotels) ? results.hotels.map(asRecord) : []
  const city = evidenceText(results.city)
  const keyword = evidenceText(results.keyword) || '酒店'
  const title = city && !keyword.startsWith(city) ? `${city} · ${keyword}` : keyword
  const summary = evidenceText(results.summary)
  const error = evidenceText(data.error)
  const budgetStatus = evidenceText(results.budget_status)
  const budget = asRecord(results.budget)
  const budgetBasis = evidenceText(budget.basis)
  const budgetNote = budgetBasis === 'stay_total' && typeof budget.nights === 'number' && budget.ceiling
    ? `住宿总额 ${budget.ceiling} 元 / ${budget.nights} 晚，按每晚参考价折算比较`
    : budgetBasis === 'nightly' && budget.ceiling
      ? `每晚参考价上限 ${budget.ceiling} 元`
      : budgetBasis === 'unverified' ? evidenceText(budget.reason) || '住宿预算口径无法核验' : ''
  const timestamp = evidenceText(results.queried_at)
  const beijing = beijingQueryTime(timestamp)
  const total = typeof results.count === 'number' && results.count > 0 ? results.count : hotels.length
  const sources = evidenceSources(results.sources, data.sources)
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  const shown = expanded ? hotels : hotels.slice(0, SHOW)

  return <FlightResult agent="hotel_search" kind="住宿候选" title={title}
    meta={total > 0 ? <span>{total >= 600 ? '共 600+ 家' : `共 ${total} 家`}</span> : undefined}>
    <EvidenceBand label="住宿地点" status="预订请以实际渠道为准" tone="neutral" sources={sources}>
      {(beijing || timestamp) && <p>{beijing ? `查询时间 ${beijing}（北京时间）` : `查询时间原文：${timestamp}`}</p>}
    </EvidenceBand>
    {budgetNote && <p className="fdr-summary"><small>预算口径：{budgetNote}（地图参考价，不是实价）</small></p>}
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
      const photo = amapPhoto(hotel.photo)
      return <li key={evidenceText(hotel.id) || index} className="fdr-hotel fdr-stay">
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
        {photo && <HotelPhoto key={photo} url={photo} name={name} />}
      </li>
    })}</ol>
  </FlightResult>
}
