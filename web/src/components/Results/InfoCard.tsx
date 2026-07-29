import { ExternalLink } from 'lucide-react'
import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'
import { WeatherIcon } from '../Illustrations'

function extractTemperature(text: string): string | null {
  const match = text.match(/(-?\d+)\s*[°℃]/)
  return match ? match[1] : null
}

export function InfoCard({ data }: { data: Record<string, unknown> }) {
  const results = data.results as Record<string, unknown> | undefined
  const summary = (results?.summary || data.summary || data.message || data.answer) as string | undefined
  const sources = (results?.sources || data.sources) as { url: string; title?: string }[] | undefined
  const isWeather = summary?.includes('°') || summary?.includes('天气') || data.type === 'weather'
  const temp = summary ? extractTemperature(summary) : null

  return (
    <CardShell agentName="information_query">
      <div className="p-4 space-y-2">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="information_query" size={16} />
          {isWeather ? '天气信息' : '搜索结果'}
        </h4>

        {/* Weather hero display */}
        {isWeather && summary && (
          <div className="flex items-center gap-4 p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
            <WeatherIcon text={summary} size={56} />
            <div className="flex-1">
              {temp && (
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-bold text-gradient">{temp}</span>
                  <span className="text-lg text-[var(--text-muted)]">°C</span>
                </div>
              )}
              <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed whitespace-pre-wrap">{summary}</p>
            </div>
          </div>
        )}

        {/* Non-weather or fallback */}
        {!isWeather && summary && <p className="text-sm whitespace-pre-wrap leading-relaxed">{summary}</p>}
        {isWeather && !summary && <p className="text-sm whitespace-pre-wrap leading-relaxed">{summary}</p>}

        {data.error != null && <p className="text-sm text-[var(--error)]">{String(data.error)}</p>}
        {sources && sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {sources.map((s, i) => (
              <a key={i} href={s.url} target="_blank" rel="noopener noreferrer"
                className="text-xs px-2.5 py-1 rounded-full flex items-center gap-1 transition-all hover:shadow-sm"
                style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}>
                <ExternalLink size={10} /> {s.title || new URL(s.url).hostname}
              </a>
            ))}
          </div>
        )}
      </div>
    </CardShell>
  )
}
