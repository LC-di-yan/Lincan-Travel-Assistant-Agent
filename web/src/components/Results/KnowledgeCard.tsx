import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Markdown } from '../Markdown'
import { CardShell } from './CardShell'
import { getAgentLabel } from '../Icons'

export function KnowledgeCard({ data, agentName }: { data: Record<string, unknown>; agentName?: string }) {
  const [showSources, setShowSources] = useState(false)
  const rawAnswer = (data.answer || data.content || data.result || data.message) as string | undefined
  const sources = data.sources as { document?: string; similarity?: number; content?: string }[] | undefined
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
    <CardShell agentName={agentName}>
      <div className="border-b border-rule px-4 py-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / KNOWLEDGE</div>
        <h4 className="mt-1 text-[15px] font-semibold text-ink">{label}</h4>
      </div>

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
                {sources.map((s, i) => (
                  <div key={i} className="border-b border-rule py-2 text-[11px] last:border-0">
                    <div className="flex items-baseline gap-2">
                      <span className="font-medium text-ink">{s.document || '文档 ' + (i + 1)}</span>
                      {s.similarity != null && (
                        <span className="font-mono tabular text-accent">{'相似度 ' + (s.similarity * 100).toFixed(1) + '%'}</span>
                      )}
                    </div>
                    {s.content && <p className="mt-1 line-clamp-2 leading-5 text-ink-3">{s.content}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </CardShell>
  )
}
