import type { AgentResult } from '../../api/types'
import { ItineraryCard } from './ItineraryCard'
import { EventCard } from './EventCard'
import { InfoCard } from './InfoCard'
import { KnowledgeCard } from './KnowledgeCard'
import { PreferenceCard } from './PreferenceCard'
import { ExpenseCard } from './ExpenseCard'
import { CurrencyCard } from './CurrencyCard'
import { TranslationCard } from './TranslationCard'
import { AlertCircle } from 'lucide-react'

function ResultCard({ result }: { result: AgentResult }) {
  if (result.status === 'error') {
    const errMsg = (result.data as any)?.error || (result.data as any)?.message || ''
    return (
      <div className="rounded-2xl border p-4 flex items-start gap-2 text-sm animate-fade-in-up"
        style={{ borderColor: 'var(--error)', backgroundColor: 'var(--error-light)' }}>
        <AlertCircle size={16} className="text-[var(--error)] mt-0.5 shrink-0" />
        <div>
          <span className="font-medium">{result.agent_name}: 执行失败</span>
          {errMsg && <p className="text-[var(--text-secondary)] mt-1">{errMsg}</p>}
        </div>
      </div>
    )
  }

  const d = result.data as Record<string, unknown>
  const inner = (d.data || d) as Record<string, unknown>
  const agent = result.agent_name

  switch (agent) {
    case 'itinerary_planning':
      return <ItineraryCard data={inner} />
    case 'event_collection':
      return <EventCard data={inner} />
    case 'information_query':
      return <InfoCard data={inner} />
    case 'rag_knowledge':
      return <KnowledgeCard data={inner} agentName={agent} />
    case 'preference':
      return <PreferenceCard data={inner} />
    case 'expense_tracker':
      return <ExpenseCard data={inner} />
    case 'currency_converter':
      return <CurrencyCard data={inner} />
    case 'memory_query':
      return <KnowledgeCard data={inner} agentName={agent} />
    case 'visa_info':
      return <KnowledgeCard data={inner} agentName={agent} />
    case 'translation':
      return <TranslationCard data={inner} />
    default:
      return <KnowledgeCard data={inner} agentName={agent} />
  }
}

export function ResultDashboard({ results }: { results: AgentResult[] }) {
  if (!results || results.length === 0) return null

  return (
    <div className="space-y-3">
      {results.map((r, i) => (
        <ResultCard key={i} result={r} />
      ))}
    </div>
  )
}
