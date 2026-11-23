import { useId, useState } from 'react'
import { MapPin } from 'lucide-react'
import { asRecord } from '../../utils/resultData'
import { amapMarker, evidenceSources, evidenceText, mapReference, publicLink } from '../../utils/flightEvidence'
import { EvidenceBand, FlightResult, ResultDisclosure } from './FlightResult'

function PlacePhoto({ url }: { url?: string }) {
  const [unavailable, setUnavailable] = useState(false)
  return <span className="fdr-place-thumb" aria-hidden="true">
    {url && !unavailable
      ? <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setUnavailable(true)} />
      : <MapPin size={19} />}
  </span>
}

export function PlaceListCard({ data, kind }: { data: Record<string, unknown>; kind: 'restaurant' | 'scenic' }) {
  const results = asRecord(data.results ?? data)
  const raw = results[kind === 'restaurant' ? 'restaurants' : 'attractions']
  const places = Array.isArray(raw) ? raw.map(asRecord) : []
  const scenic = kind === 'scenic'
  const label = scenic ? '景点清单' : '餐饮清单'
  const unit = scenic ? '个' : '家'
  const city = evidenceText(results.city)
  const keyword = evidenceText(results.keyword) || (scenic ? '景点' : '餐饮')
  const title = city && !keyword.startsWith(city) ? `${city} · ${keyword}` : keyword
  const count = typeof results.count === 'number' && results.count > 0 ? results.count : places.length
  const summary = evidenceText(results.summary)
  const error = evidenceText(data.error)
  const sources = evidenceSources(results.sources, data.sources)
  const [expanded, setExpanded] = useState(false)
  const id = useId()
  const shown = expanded ? places : places.slice(0, 5)

  return <FlightResult agent={scenic ? 'scenic_search' : 'restaurant_search'} kind={label} title={title}
    meta={count > 0 ? <span>共 {count >= 600 ? '600+' : count} {unit}</span> : undefined}>
    <EvidenceBand label="地点" status={sources.length ? '地点资料来源' : '来源未提供'} tone="neutral" sources={sources}>
      {places.length > 0 && <p>评分、距离和参考费用以来源为准；营业时间和现场价格请另行核验。</p>}
    </EvidenceBand>
    {summary && <p className="fdr-summary">{summary}</p>}
    {error && error !== summary && <p className="fdr-summary" data-error>{error}</p>}
    {!places.length && !summary && !error && <p className="fdr-empty">{scenic
      ? '未找到相关景点信息，请尝试更换城市或关键词' : '未找到相关餐厅信息，请尝试更换城市或菜系关键词'}</p>}
    {places.length > 0 && <div className="fdr-section-head">
      <h4>地点与地址 <small>显示 {shown.length} / {places.length} {unit}</small></h4>
      {places.length > 5 && <ResultDisclosure open={expanded} controls={id} onToggle={() => setExpanded(!expanded)}>
        {expanded ? '收起地点' : `查看全部 ${places.length} ${unit}`}
      </ResultDisclosure>}
    </div>}
    <ol className="fdr-hotels" id={id}>{shown.map((place, index) => {
      const name = evidenceText(place.name) || '地点名称未提供'
      const url = amapMarker(place.location, name)
      const photo = publicLink(place.photo)
      const rating = Number(place.rating)
      const distance = Number(place.distance)
      const price = mapReference(place.cost)
      return <li key={index} className="fdr-hotel fdr-place">
        <PlacePhoto url={photo} key={photo || index} />
        <div className="fdr-hotel-name">
          <h5>{name}</h5>
          <p>{evidenceText(place.address) || '地址未提供'}</p>
          <p className="fdr-hotel-meta">
            {Number.isFinite(rating) && rating > 0 && <span>评分 {String(place.rating)}</span>}
            {Number.isFinite(distance) && distance > 0 && <span>距搜索点 {distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${Math.round(distance)} m`}</span>}
          </p>
          {url && <a className="fdr-inline-link" href={url} target="_blank" rel="noopener noreferrer" aria-label={`在高德打开：${name}`}>
            <MapPin size={14} aria-hidden="true" /> 在高德打开
          </a>}
        </div>
        {price.kind !== 'missing' && <div className="fdr-hotel-price" data-unknown={price.kind !== 'reference' || undefined}>
          <strong>{price.kind === 'reference' ? <>参考 <span className="fdr-price-number">{price.raw}</span></> : '费用待核验'}</strong>
          <small>{price.kind === 'unclear' ? `来源原文：${price.raw}` : scenic ? '不是门票报价' : '不是实付金额'}</small>
        </div>}
      </li>
    })}</ol>
  </FlightResult>
}
