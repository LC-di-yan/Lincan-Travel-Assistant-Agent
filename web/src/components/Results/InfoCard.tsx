import { EvidenceBand, FlightResult } from './FlightResult'
import { WeatherIcon } from '../Illustrations'
import { evidenceSources } from '../../utils/flightEvidence'

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function temperature(value: unknown): string {
  const number = typeof value === 'number' ? String(value) : text(value)
  return /^[+-]?\d+(?:\.\d+)?$/.test(number) && Number.isFinite(Number(number)) ? number : ''
}

type WeatherAdvice = {
  date: string
  dateIso: string
  travelTips: string
  clothingAdvice: string
}

function AdviceDetails({ advice }: { advice: WeatherAdvice[] }) {
  if (advice.length === 0) return null
  return (
    <div className="mt-2 space-y-1 text-[12px] leading-6 text-ink-2">
      {advice.map((item, i) => (
        <div key={i}>
          {item.travelTips && <p><span className="font-medium text-ink">出行提醒：</span>{item.travelTips}</p>}
          {item.clothingAdvice && <p><span className="font-medium text-ink">穿衣建议：</span>{item.clothingAdvice}</p>}
        </div>
      ))}
    </div>
  )
}

function comparable(value: string): string {
  return value.replace(/℃/g, '°C').replace(/：/g, ':').replace(/\s+/g, '')
}

// 旧会话没有独立建议字段，只移除确实已排版的事实片段，保留其后的独有提醒。
function stripPrefix(value: string, prefix: string): string | undefined {
  const expected = comparable(prefix)
  if (!expected || !comparable(value).startsWith(expected)) return undefined
  for (let end = 1; end <= value.length; end++) {
    if (comparable(value.slice(0, end)) === expected) {
      return value.slice(end).replace(/^[\s，,；;。]+/, '')
    }
  }
  return undefined
}

function legacyWeatherSummary(
  summary: string,
  city: string,
  rangeLabel: string,
  current: Record<string, unknown>,
  showCurrent: boolean,
  forecast: Record<string, unknown>[],
  renderedTexts: string[],
): string {
  const currentTemp = temperature(current.temp)
  const humidity = temperature(current.humidity)
  const currentDetails = [text(current.wind), humidity && `湿度 ${humidity}%`].filter(Boolean).join('，')
  const lines = summary.split(/\r?\n/).flatMap((rawLine) => {
    const line = rawLine.trim().replace(/^[\p{Extended_Pictographic}\uFE0F\u200D\s]+/u, '')
    if (!line) return []
    if (renderedTexts.some((value) => comparable(line) === comparable(value))) return []
    if (renderedTexts.some((value) => {
      const suffix = comparable(value)
      const content = comparable(line)
      return suffix && content.endsWith(suffix) && /(?:出行提醒|穿衣建议|交通建议)(?:[（(][^）)]*[）)])?:$/.test(content.slice(0, -suffix.length))
    })) return []
    if (city && rangeLabel && comparable(line) === comparable(`${city}天气【${rangeLabel}】`)) return []
    if (forecast.length > 0 && /^(?:今日全天预报|所查日期预报)$/.test(line)) return []
    const observation = line.match(/^当前实况[（(](.+)[）)]$/)
    // 旧摘要的时间来自查询时钟，不能把它当成气象站观测时间。
    if (observation && currentTemp) return showCurrent ? [`查询时间：${observation[1]}`] : []
    if (currentTemp && comparable(line) === comparable(`${text(current.weather)}，气温 ${currentTemp}°C`)) return []
    if (currentTemp && currentDetails && comparable(line) === comparable(currentDetails)) return []

    for (const day of forecast) {
      const label = text(day.date) || text(day.date_iso)
      const range = text(day.temp_range)
      if (!range) continue
      const generated = `${label}：白天${text(day.weather)}，夜间${text(day.night_weather)}，气温 ${range}`
      const extra = stripPrefix(line, generated)
      if (extra !== undefined) return extra && comparable(extra) !== comparable(text(day.description)) ? [`${label}提醒：${extra}`] : []
      const relative = text(day.date).match(/^(今天|明天|后天)/)?.[1]
      const labels = [label, text(day.date_iso), relative, relative === '今天' ? '今日' : ''].filter((value): value is string => Boolean(value))
      for (const date of labels) {
        for (const prefix of [`${date}气温 ${range}`, `${date}天气 ${range}`, `${date}全天预报 ${range}`]) {
          const remaining = stripPrefix(line, prefix)
          if (remaining !== undefined) return remaining ? [remaining] : []
        }
      }
    }
    return [rawLine.trim()]
  })
  return lines.join('\n')
}

export function InfoCard({ data }: { data: Record<string, unknown> }) {
  const results = record(data.results)
  const summary = text(results.summary) || text(results.message) || text(data.summary) || text(data.message) || text(data.answer)
  const sources = evidenceSources(results.sources, data.sources)
  const requested = record(results.requested_range || data.requested_range)
  const current = record(results.current || data.current)
  const startDate = text(requested.start_date)
  const endDate = text(requested.end_date)
  const hasDateRange = /^\d{4}-\d{2}-\d{2}$/.test(startDate) && /^\d{4}-\d{2}-\d{2}$/.test(endDate)
  const rawForecast = results.forecast || data.forecast
  const forecast = (Array.isArray(rawForecast) ? rawForecast : []).map(record).filter((day) => {
    const date = text(day.date_iso)
    // 有明确查询范围时，只突出日期可验证且确实属于该范围的预报。
    return hasDateRange
      ? /^\d{4}-\d{2}-\d{2}$/.test(date) && date >= startDate && date <= endDate
      : Boolean(date || text(day.date))
  })
  const isTransportOnly = data.query_type === '交通建议' || data.type === 'transport'
  const isWeather = !isTransportOnly && (
    data.query_type === '天气查询' || data.type === 'weather' ||
    Object.keys(requested).length > 0 || Object.keys(current).length > 0 || forecast.length > 0
  )
  const isMultiDay = (hasDateRange && startDate !== endDate) || forecast.length > 1
  // 绝不从摘要推断实况温度：区间末端、未来预报和交通建议都不是当前气温。
  const currentDate = text(current.date_iso) || text(current.date).match(/^\d{4}-\d{2}-\d{2}$/)?.[0] || ''
  const currentMatchesRange = currentDate
    ? !hasDateRange || currentDate >= startDate && currentDate <= endDate
    : !hasDateRange || isMultiDay || /^(?:今天|今日|当前|实时)/.test(text(requested.label))
  const includedCurrentTemp = isWeather && requested.include_current === true && currentMatchesRange ? temperature(current.temp) : ''
  const currentTemp = !isMultiDay ? includedCurrentTemp : ''
  // 多日请求保留本次实况，但使用紧凑行，不能拿单点大号温度代表整个区间。
  const compactCurrentTemp = isMultiDay ? includedCurrentTemp : ''
  const isForecast = isMultiDay || requested.include_current === false || forecast.length > 0 && !currentTemp
  const dates = hasDateRange ? startDate === endDate ? startDate : `${startDate} 至 ${endDate}` : ''
  const rangeLabel = text(requested.label)
  const weatherContext = [rangeLabel, dates && !rangeLabel.includes(dates) ? dates : ''].filter(Boolean).join(' · ')
  const error = results.error ?? data.error
  const humidity = temperature(current.humidity)
  const rawAdvice = results.advice || data.advice
  const advice: WeatherAdvice[] = (Array.isArray(rawAdvice) ? rawAdvice : []).map(record).filter((item) => {
    const date = text(item.date_iso)
    return !hasDateRange || !date || date >= startDate && date <= endDate
  }).map((item) => ({
    date: text(item.date), dateIso: text(item.date_iso),
    travelTips: text(item.travel_tips), clothingAdvice: text(item.clothing_advice),
  })).filter((item) => item.travelTips || item.clothingAdvice)
  const rawNotes = results.weather_notes || data.weather_notes
  const notes = Array.isArray(rawNotes) ? [...new Set(rawNotes.map(text).filter((note) => note && (error == null || comparable(note) !== comparable(String(error)))))] : []
  const transportSummary = text(record(results.transport_advice || data.transport_advice).summary)
  const hasStructuredWeather = Boolean(includedCurrentTemp) || forecast.some((day) =>
    ['weather', 'night_weather', 'temp_range', 'description'].some((key) => text(day[key])),
  ) || advice.length > 0 || notes.length > 0
  const formattedWeather = isWeather && Number(results.presentation_version ?? data.presentation_version) >= 2 && hasStructuredWeather
  // 新结果只消费一份结构化内容；结构缺失时仍安全回退到人话摘要，避免空卡。
  const summaryWithoutTransport = transportSummary ? summary.replaceAll(transportSummary, '').trim() : summary
  const renderedTexts = [...advice.flatMap((item) => [item.travelTips, item.clothingAdvice]), ...notes, error == null ? '' : String(error)].filter(Boolean)
  const remainingSummary = formattedWeather ? '' : isWeather ? legacyWeatherSummary(
    summaryWithoutTransport, text(results.city || data.city), rangeLabel, current, Boolean(includedCurrentTemp), forecast, renderedTexts,
  ) : summaryWithoutTransport
  const unassignedAdvice = advice.filter((item) => !forecast.some((day) => text(day.date_iso) === item.dateIso && item.dateIso))
  const hasWeatherDetails = Boolean(includedCurrentTemp) || isWeather && forecast.length > 0

  return (
    <FlightResult agent="information_query" kind={isWeather ? isForecast ? '天气预报' : '天气信息' : '查询结果'}
      title={isWeather ? (text(results.city || data.city) ? `${text(results.city || data.city)} · 天气简报` : '天气简报') : '搜索结果'}
      meta={isWeather && weatherContext ? <span>{weatherContext}</span> : undefined}>
      {(sources.length > 0 || isWeather) && <EvidenceBand tone="neutral" label="资料"
        status={isWeather ? (sources.length ? '天气资料来源' : '来源未提供') : '查询资料来源'} sources={sources} />}

      <div className="fdr-weather-body">
        {compactCurrentTemp && (
          <section className="fdr-weather-live fdr-weather-compact" aria-label="观测实况">
            <p className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-medium text-ink">本次实况</span>
              {(text(current.date) || currentDate) && <span className="text-[11px] text-ink-3">{text(current.date) || currentDate}</span>}
              <span className="font-mono tabular text-accent">{compactCurrentTemp}°C</span>
              {text(current.weather) && <span>{text(current.weather)}</span>}
            </p>
            {(text(current.wind) || humidity) && <p className="text-[11px] text-ink-3">{[text(current.wind), humidity && `湿度 ${humidity}%`].filter(Boolean).join(' · ')}</p>}
            {text(current.observed_at) && <p className="text-[11px] text-ink-3">观测时间：{text(current.observed_at)}</p>}
          </section>
        )}

        {currentTemp && (
          <section className="fdr-weather-live flex items-center gap-4" aria-label="观测实况">
            <WeatherIcon text={text(current.weather)} size={48} />
            <div className="min-w-0 flex-1">
              <p className="text-[11px] text-ink-3">当前实况</p>
              <div className="mt-1 flex items-baseline gap-1">
                <span className="font-mono text-[32px] font-semibold tabular leading-none text-accent">{currentTemp}</span>
                <span className="text-[14px] text-ink-3">°C</span>
              </div>
              {text(current.weather) && <p className="mt-1 text-[12px] text-ink-2">{text(current.weather)}</p>}
              {(text(current.wind) || humidity) && (
                <p className="mt-1 text-[11px] text-ink-3">
                  {[text(current.wind), humidity && `湿度 ${humidity}%`].filter(Boolean).join(' · ')}
                </p>
              )}
              {text(current.observed_at) && <p className="mt-1 text-[11px] text-ink-3">观测时间：{text(current.observed_at)}</p>}
            </div>
          </section>
        )}

        {isWeather && forecast.length > 0 && (
          <section className="fdr-weather-forecast" aria-label="按日预报">
            <h4>按日预报 <span>日期 · 天气 · 温度范围</span></h4>
            {forecast.map((day, i) => (
              <div key={text(day.date_iso) || i} className="fdr-forecast-row">
                <div className="fdr-forecast-reading">
                  <time dateTime={text(day.date_iso) || undefined}>{text(day.date) || text(day.date_iso)}</time>
                  <span className="fdr-forecast-conditions">
                    {[text(day.weather) && `白天${text(day.weather)}`, text(day.night_weather) && `夜间${text(day.night_weather)}`].filter(Boolean).join(' / ')}
                  </span>
                  <span className="fdr-forecast-range">{text(day.temp_range) || '温度范围未提供'}</span>
                </div>
                {text(day.description) && <p className="mt-1 text-[12px] leading-6 text-ink-3">{text(day.description)}</p>}
                <AdviceDetails advice={advice.filter((item) => item.dateIso === text(day.date_iso) && Boolean(item.dateIso))} />
              </div>
            ))}
          </section>
        )}

        {isWeather && unassignedAdvice.map((item, i) => (
          <div key={i} className={hasWeatherDetails || i > 0 ? 'mt-3' : ''}>
            {(item.date || item.dateIso) && <p className="text-[12px] font-medium text-ink">{item.date || item.dateIso}</p>}
            <AdviceDetails advice={[item]} />
          </div>
        ))}

        {isWeather && notes.length > 0 && <div className={hasWeatherDetails || advice.length > 0 ? 'mt-3 space-y-1' : 'space-y-1'}>
          {notes.map((note, i) => <p key={i} className="text-[12px] leading-6 text-ink-3">{note}</p>)}
        </div>}

        {remainingSummary && <p className={`${hasWeatherDetails ? 'mt-3 ' : ''}whitespace-pre-wrap text-[13px] leading-6 text-ink-2`}>{remainingSummary}</p>}

        {transportSummary && <section aria-label="市内交通建议"
          className={`${hasWeatherDetails || remainingSummary || advice.length > 0 || notes.length > 0 ? 'mt-3 border-t border-rule pt-3 ' : ''}text-[13px] leading-6 text-ink-2`}>
          <h4 className="font-semibold text-ink">出行参考 <span className="text-xs font-normal text-ink-3">不代表实时线路</span></h4>
          <p className="whitespace-pre-wrap">{transportSummary}</p>
        </section>}

        {error != null && <p className="mt-2 text-[12px] text-err">{String(error)}</p>}

      </div>
    </FlightResult>
  )
}
