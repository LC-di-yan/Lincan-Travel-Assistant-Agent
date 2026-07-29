import { BookOpen, ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { CardShell } from './CardShell'
import { AgentIcon, getAgentLabel } from '../Icons'

export function KnowledgeCard({ data, agentName }: { data: Record<string, unknown>; agentName?: string }) {
  const [showSources, setShowSources] = useState(false)
  const answer = (data.answer || data.content || data.result || data.message) as string | undefined
  const sources = data.sources as { document?: string; similarity?: number; content?: string }[] | undefined
  const label = agentName ? getAgentLabel(agentName) : '知识库回答'

  if (!answer) return null

  return (
    <CardShell agentName={agentName}>
      <div className="p-4 space-y-2.5">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          {agentName ? <AgentIcon agentName={agentName} size={16} /> : <BookOpen size={14} className="text-[var(--accent)]" />}
          {label}
        </h4>
        <div className="text-sm prose prose-sm max-w-none dark:prose-invert overflow-x-auto break-words">
          <ReactMarkdown>{answer}</ReactMarkdown>
        </div>

        {sources && sources.length > 0 && (
          <div className="mt-2">
            <button onClick={() => setShowSources(!showSources)}
              className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors">
              {showSources ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              来源文档 ({sources.length})
            </button>
            {showSources && (
              <div className="mt-2 space-y-1.5">
                {sources.map((s, i) => (
                  <div key={i} className="text-xs p-2.5 rounded-xl"
                    style={{ backgroundColor: 'var(--bg-secondary)' }}>
                    <span className="font-medium">{s.document || `文档 ${i + 1}`}</span>
                    {s.similarity != null && (
                      <span className="ml-2 text-[var(--accent)]">
                        相似度: {(s.similarity * 100).toFixed(1)}%
                      </span>
                    )}
                    {s.content && <p className="mt-1 text-[var(--text-muted)] line-clamp-2">{s.content}</p>}
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
