import { lazy, Suspense } from 'react'
import type { AgentResult } from '../../api/types'
import type { ProposalActions } from './TripPlanCard'
import { getAgentLabel } from '../Icons'
import { AlertCircle } from 'lucide-react'
import { Markdown } from '../Markdown'
import { getResultPresentation, type ResultPresentation } from '../../utils/resultPresentation'

const TripPlanCard = lazy(() => import('./TripPlanCard'))
const ItineraryCard = lazy(() => import('./ItineraryCard').then(m => ({ default: m.ItineraryCard })))
const HotelCard = lazy(() => import('./HotelCard').then(m => ({ default: m.HotelCard })))
const TrainCard = lazy(() => import('./TrainCard').then(m => ({ default: m.TrainCard })))
const InfoCard = lazy(() => import('./InfoCard').then(m => ({ default: m.InfoCard })))
const ExpenseCard = lazy(() => import('./ExpenseCard').then(m => ({ default: m.ExpenseCard })))
const PlaceListCard = lazy(() => import('./PlaceListCard').then(m => ({ default: m.PlaceListCard })))
const EventCard = lazy(() => import('./EventCard').then(m => ({ default: m.EventCard })))
const CurrencyCard = lazy(() => import('./CurrencyCard').then(m => ({ default: m.CurrencyCard })))
const TranslationCard = lazy(() => import('./TranslationCard').then(m => ({ default: m.TranslationCard })))
const KnowledgeCard = lazy(() => import('./KnowledgeCard').then(m => ({ default: m.KnowledgeCard })))
const PreferenceCard = lazy(() => import('./PreferenceCard').then(m => ({ default: m.PreferenceCard })))

interface ExpenseActions {
  confirmation?: { command: string; submit: () => void }
  pending?: string
  fresh?: boolean
}

function PrimaryResultCard({ result, presentation, proposal, expense }: {
  result: AgentResult; presentation: ResultPresentation; proposal?: ProposalActions; expense?: ExpenseActions
}) {
  const inner = presentation.data
  if (presentation.kind === 'error') {
    const detail = inner
    const errMsg = String(detail?.error || detail?.message || '')
    return (
      <div className="flex items-start gap-2 rounded-[2px] border border-err/30 bg-error-light p-3 text-[12px]">
        <AlertCircle size={14} className="mt-0.5 shrink-0 text-err" aria-hidden="true" />
        <div>
          <span className="font-medium text-ink">{result.label || getAgentLabel(result.agent_name)}{result.node_status ? ' · ' : ' '}{
            ({ skipped: '已跳过', unavailable: '不可用', timeout: '超时', cancelled: '已取消' } as Record<string, string>)[result.node_status || ''] || '执行失败'
          }</span>
          {errMsg && <p className="mt-1 leading-5 text-ink-2">{errMsg}</p>}
        </div>
      </div>
    )
  }

  const agent = result.agent_name

  switch (presentation.kind) {
    case 'trip-plan':
      return <TripPlanCard data={inner} actions={proposal} />
    case 'itinerary':
      return <ItineraryCard data={inner} />
    case 'event':
      return <EventCard data={inner} />
    case 'information':
      return <InfoCard data={inner} />
    case 'knowledge':
      return <KnowledgeCard data={inner} agentName={agent} />
    case 'preference':
      return <PreferenceCard data={inner} />
    case 'expense':
      return <ExpenseCard data={inner} fresh={expense?.fresh} submitting={!!expense?.pending && inner.confirmation_command === expense.pending}
        onConfirm={expense?.confirmation && inner.confirmation_command === expense.confirmation.command
          ? expense.confirmation.submit : undefined} />
    case 'currency':
      return <CurrencyCard data={inner} />
    case 'translation':
      return <TranslationCard data={inner} />
    case 'hotel':
      return <HotelCard data={inner} />
    case 'restaurant':
    case 'scenic':
      return <PlaceListCard data={inner} kind={presentation.kind} />
    case 'train':
      return <TrainCard data={inner} />
    default:
      return <KnowledgeCard data={inner} agentName={agent} />
  }
}

function ResultCard({ result, proposal, expense }: { result: AgentResult; proposal?: ProposalActions; expense?: ExpenseActions }) {
  const presentation = getResultPresentation(result)
  return (
    <div className="space-y-2">
      <Suspense fallback={<p className="text-sm text-ink-3">正在加载结果…</p>}>
        <PrimaryResultCard result={result} presentation={presentation} proposal={proposal} expense={expense} />
      </Suspense>
      {presentation.supplementalTexts?.map((note, index) => (
        <div key={index} className="markdown border-l-2 border-rule px-3 text-[12px] leading-6 text-ink-2">
          <Markdown>{note}</Markdown>
        </div>
      ))}
    </div>
  )
}

export function ResultDashboard({ results, proposal, expense }: {
  results: AgentResult[]; proposal?: ProposalActions; expense?: ExpenseActions
}) {
  if (!results || results.length === 0) return null

  return (
    <div className="space-y-3">
      {results.map((r, i) => (
        <ResultCard key={r.node_id ? 'node:'+r.node_id : 'legacy:'+i} result={r} proposal={proposal} expense={expense} />
      ))}
    </div>
  )
}
