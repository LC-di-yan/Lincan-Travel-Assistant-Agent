import type { AgentResult } from '../../api/types'
import { ItineraryCard } from './ItineraryCard'
import { EventCard } from './EventCard'
import { InfoCard } from './InfoCard'
import { KnowledgeCard } from './KnowledgeCard'
import { PreferenceCard } from './PreferenceCard'
import { ExpenseCard } from './ExpenseCard'
import { CurrencyCard } from './CurrencyCard'
import { TranslationCard } from './TranslationCard'
import { HotelCard } from './HotelCard'
import { RestaurantCard } from './RestaurantCard'
import { ScenicCard } from './ScenicCard'
import { getAgentLabel } from '../Icons/AgentIcon'
import { AlertCircle } from 'lucide-react'

function ResultCard({ result }: { result: AgentResult }) {
  if (result.status === 'error') {
    const errMsg = (result.data as any)?.error || (result.data as any)?.message || ''
    return (
      <div className="flex items-start gap-2 rounded-[2px] border border-err/30 bg-error-light p-3 text-[12px]">
        <AlertCircle size={14} className="mt-0.5 shrink-0 text-err" aria-hidden="true" />
        <div>
          <span className="font-medium text-ink">{getAgentLabel(result.agent_name)} 执行失败</span>
          {errMsg && <p className="mt-1 leading-5 text-ink-2">{errMsg}</p>}
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
    case 'expense_tracking':
      return <ExpenseCard data={inner} />
    case 'currency_converter':
    case 'currency_conversion':
      return <CurrencyCard data={inner} />
    case 'memory_query':
      return <KnowledgeCard data={inner} agentName={agent} />
    case 'visa_info':
      return <KnowledgeCard data={inner} agentName={agent} />
    case 'translation':
      return <TranslationCard data={inner} />
    case 'hotel_search':
      return <HotelCard data={inner} />
    case 'restaurant_search':
      return <RestaurantCard data={inner} />
    case 'scenic_search':
      return <ScenicCard data={inner} />
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
