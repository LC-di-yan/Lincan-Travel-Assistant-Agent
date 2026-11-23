import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Markdown } from '../Markdown'
import { EvidenceBand, FlightResult } from './FlightResult'
import { evidenceSources, evidenceText } from '../../utils/flightEvidence'
import { asRecord } from '../../utils/resultData'
import { getAgentLabel } from '../Icons'

export function KnowledgeCard({ data, agentName }: { data: Record<string, unknown>; agentName?: string }) {
  const [showSources, setShowSources] = useState(false)
  const rawAnswer = (data.answer || data.content || data.result || data.message) as string | undefined
  const sources = Array.isArray(data.sources) ? data.sources.map(asRecord) : []
  const entries = sources.map((row, i) => ({
    title: evidenceText(row.document) || evidenceText(row.title) || `文档 ${i + 1}`, url: row.url, content: evidenceText(row.content),
  }))
  const label = agentName ? getAgentLabel(agentName) : '知识库回答'

  let answer = rawAnswer
  if (answer && typeof answer === 'string') {
    const trimmed = answer.trim()
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          answer = (parsed.answer || parsed.response || parsed.content || parsed.result || parsed.message || answer) as string
        }
      } catch {
        /* use as-is */
      }
    }
  }

  if (!answer) return null

  return (
    <FlightResult agent={agentName || 'knowledge'} kind="KNOWLEDGE" title={label}>
      {entries.length > 0 && <EvidenceBand label="证据" status="本轮参考资料" tone="neutral" sources={evidenceSources(entries)} />}

      <div className="px-4 py-3">
        <div className="markdown max-w-none overflow-x-auto break-words">
          <Markdown>{answer}</Markdown>
        </div>

        {sources && sources.length > 0 && (
          <div className="mt-3 border-t border-rule pt-2.5">
            <button
              type="button"
              onClick={() => setShowSources((v) => !v)}
              aria-expanded={showSources}
              className="flex items-center gap-1 text-[11px] text-ink-3 hover:text-accent"
            >
              {showSources ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />}
              来源文档（{sources.length}）
            </button>
            {showSources && (
              <div className="mt-2">
                {entries.map((s, i) => (
                  <div key={i} className="border-b border-rule py-2 text-[11px] last:border-0">
                    <div className="flex items-baseline gap-2">
                      <span className="font-medium text-ink">{s.title}</span>
                    </div>
                    {s.content && <p className="mt-1 whitespace-pre-wrap leading-5 text-ink-3">{s.content}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </FlightResult>
  )
}
