import { ExternalLink } from 'lucide-react'
import { CardShell } from './CardShell'
import { WeatherIcon } from '../Illustrations'

function extractTemperature(text: string): string | null {
  const match = text.match(/(-?\d+)\s*[°℃]/)
  return match ? match[1] : null
}

function sourceLabel(source: { url?: string; title?: string }): string {
  if (source.title) return source.title
  try {
    return new URL(source.url || '').hostname || '来源'
  } catch {
    return source.url || '来源'
  }
}

export function InfoCard({ data }: { data: Record<string, unknown> }) {
  const results = data.results as Record<string, unknown> | undefined
  const summary = (results?.summary || data.summary || data.message || data.answer) as string | undefined
  const sources = (results?.sources || data.sources) as { url: string; title?: string }[] | undefined
  const isWeather = summary?.includes('°') || summary?.includes('天气') || data.type === 'weather'
  const temp = summary ? extractTemperature(summary) : null

  return (
    <CardShell agentName="information_query">
      <div className="border-b border-rule px-4 py-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / INFO</div>
        <h4 className="mt-1 text-[15px] font-semibold text-ink">{isWeather ? '天气信息' : '搜索结果'}</h4>
      </div>

      <div className="px-4 py-3">
        {isWeather && summary ? (
          <div className="flex items-center gap-4">
            <WeatherIcon text={summary} size={48} />
            <div className="min-w-0 flex-1">
              {temp && (
                <div className="flex items-baseline gap-1">
                  <span className="font-mono text-[32px] font-semibold tabular leading-none text-accent">{temp}</span>
                  <span className="text-[14px] text-ink-3">°C</span>
                </div>
              )}
              <p className="mt-1 whitespace-pre-wrap text-[12px] leading-6 text-ink-2">{summary}</p>
            </div>
          </div>
        ) : (
          summary && <p className="whitespace-pre-wrap text-[13px] leading-6 text-ink-2">{summary}</p>
        )}

        {data.error != null && <p className="mt-2 text-[12px] text-err">{String(data.error)}</p>}

        {sources && sources.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-rule pt-2.5">
            {sources.map((s, i) => (
              <a
                key={i}
                href={s.url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 rounded-[2px] border border-rule px-2 py-1 text-[10px] text-ink-3 hover:text-accent"
              >
                <ExternalLink size={9} aria-hidden="true" /> {sourceLabel(s)}
              </a>
            ))}
          </div>
        )}
      </div>
    </CardShell>
  )
}
