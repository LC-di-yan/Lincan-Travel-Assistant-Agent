import { lazy } from 'react'
import { ChevronDown } from 'lucide-react'
import type { AgentResult } from '../../api/types'
import type { ProposalActions } from './TripPlanCard'
import { getAgentLabel } from '../Icons'
import { AlertCircle } from 'lucide-react'
import { Markdown } from '../Markdown'
import { DeferredRegion } from '../Layout/DeferredRegion'
import { SkeletonShimmer } from '../effects/SkeletonShimmer'
import { getResultPresentation, type ResultPresentation } from '../../utils/resultPresentation'
import { expenseCancellation } from '../../utils/expenseEvidence'

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
  confirmation?: { command: string; submit: () => void; cancel: () => void }
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
    case 'expense': {
      const confirmation = expense?.confirmation
      const actions = confirmation && inner.confirmation_command === confirmation.command ? confirmation : undefined
      const cancelling = typeof inner.confirmation_command === 'string' && expense?.pending === expenseCancellation(inner.confirmation_command)
      return <ExpenseCard data={inner} fresh={expense?.fresh}
        submitting={!!expense?.pending && inner.confirmation_command === expense.pending}
        cancelling={cancelling} onConfirm={actions?.submit} onDecline={actions?.cancel} />
    }
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
      <DeferredRegion label="这条结果" fallback={<SkeletonShimmer label="正在加载这条结果" />}>
        <PrimaryResultCard result={result} presentation={presentation} proposal={proposal} expense={expense} />
      </DeferredRegion>
      {presentation.supplementalTexts?.map((note, index) => (
        <div key={index} className="markdown border-l-2 border-rule px-3 text-[12px] leading-6 text-ink-2">
          <Markdown>{note}</Markdown>
        </div>
      ))}
    </div>
  )
}

const EVIDENCE_LABELS: Record<string, string> = {
  information: '天气 / 信息',
  hotel: '住宿',
  restaurant: '餐饮',
  scenic: '景点',
  train: '车次',
  itinerary: '行程',
  knowledge: '资料',
  event: '要素',
  preference: '偏好',
  expense: '账目',
  currency: '汇率',
  translation: '翻译',
  error: '失败项',
}

function summarizeEvidence(results: AgentResult[]): string {
  const counts = new Map<string, number>()
  for (const result of results) {
    const kind = getResultPresentation(result).kind
    // 证据横条按卡片类型归并（住宿 / 天气 / 车次 ×2），比“查询去程交通”这类任务名更好扫读。
    const label = EVIDENCE_LABELS[kind] || result.label || getAgentLabel(result.agent_name)
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return [...counts.entries()].map(([label, count]) => count > 1 ? label + ' ×' + count : label).join(' · ')
}

export function ResultDashboard({ results, proposal, expense }: {
  results: AgentResult[]; proposal?: ProposalActions; expense?: ExpenseActions
}) {
  if (!results || results.length === 0) return null

  // 方案卡本身已经包含去程、住宿与费用；把支撑它的证据收进一条可展开的横条，
  // 避免一次规划把天气、住宿、往返车次全部铺满整屏。
  const planIndex = results.findIndex((result) => getResultPresentation(result).kind === 'trip-plan')
  const plan = planIndex >= 0 ? results[planIndex] : undefined
  const evidence = plan ? results.filter((_, index) => index !== planIndex) : results
  const summary = summarizeEvidence(evidence)
  const keyOf = (result: AgentResult, index: number) => result.node_id ? 'node:' + result.node_id : 'legacy:' + index

  const stack = <>
    {plan && <ResultCard key={keyOf(plan, planIndex)} result={plan} proposal={proposal} expense={expense} />}
    {plan && evidence.length > 1 ? (
      <details className="group rounded-[2px] border border-rule bg-paper-raised">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs text-ink-2 [&::-webkit-details-marker]:hidden">
          <ChevronDown size={14} aria-hidden="true" className="shrink-0 transition-transform group-open:rotate-180" />
          <span className="shrink-0 font-semibold text-ink">本轮核验的证据</span>
          <span className="min-w-0 truncate text-ink-3">{summary}</span>
          <span className="ml-auto shrink-0 font-mono tabular text-ink-3">{evidence.length} 项</span>
        </summary>
        <div className="space-y-3 border-t border-rule p-2 sm:p-3">
          {evidence.map((result, index) => (
            <ResultCard key={keyOf(result, index)} result={result} proposal={proposal} expense={expense} />
          ))}
        </div>
      </details>
    ) : evidence.map((result, index) => (
      <ResultCard key={keyOf(result, index)} result={result} proposal={proposal} expense={expense} />
    ))}
  </>

  return <div className="space-y-3">{stack}</div>
}
