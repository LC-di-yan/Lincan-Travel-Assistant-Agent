import { useRef, useEffect, useState, useMemo } from 'react'
import { Loader2, CheckCircle2, XCircle } from 'lucide-react'
import { getAgentLabel } from '../Icons/AgentIcon'
import type { IntentionData, AgentResult } from '../../api/types'

interface NarrativeTimelineProps {
  intention: IntentionData | null
  results: AgentResult[]
  running: string[]
}

interface NarrativeLine {
  id: string
  agentName: string
  text: string
  status: 'done' | 'active' | 'pending' | 'error'
  result?: AgentResult
}

export function NarrativeTimeline({ intention, results, running }: NarrativeTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [results.length, running.length])

  const lines = useMemo(() => buildNarrativeLines(intention, results, running), [intention, results, running])

  if (lines.length === 0) {
    return (
      <div className="px-4 py-2 text-xs text-[var(--text-muted)] flex items-center gap-2">
        <Loader2 size={12} className="animate-spin text-[var(--accent)]" />
        正在分析意图...
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="px-4 py-2 space-y-1.5 max-h-48 overflow-y-auto text-xs">
      {lines.map((line, i) => (
        <NarrativeLine key={line.id} line={line} isLatest={i === lines.length - 1} />
      ))}
    </div>
  )
}

function NarrativeLine({ line, isLatest }: { line: NarrativeLine; isLatest: boolean }) {
  const fullText = line.text
  const isActive = line.status === 'active'
  const isDone = line.status === 'done'
  const isError = line.status === 'error'

  return (
    <div
      className="flex items-start gap-2 text-xs"
      style={{ opacity: line.status === 'pending' ? 0.4 : 1 }}
    >
      {/* 状态图标 */}
      <span className="mt-0.5 flex-shrink-0">
        {isDone && <CheckCircle2 size={12} className="text-green-500" />}
        {isError && <XCircle size={12} className="text-red-400" />}
        {isActive && <Loader2 size={12} className="animate-spin text-[var(--accent)]" />}
        {line.status === 'pending' && <span className="block w-3 h-3 rounded-full border-2 border-[var(--border)]" />}
      </span>

      {/* 文字 */}
      <span className={isError ? 'text-red-400' : 'text-[var(--text-secondary)]'}>
        {isActive && isLatest ? (
          <TypewriterText text={fullText} enabled={isActive} />
        ) : (
          fullText
        )}
      </span>
    </div>
  )
}

function TypewriterText({ text, enabled }: { text: string; enabled: boolean }) {
  const [displayed, setDisplayed] = useState('')
  const idxRef = useRef(0)

  useEffect(() => {
    if (!enabled) {
      setDisplayed(text)
      return
    }
    idxRef.current = 0
    setDisplayed('')
    const timer = setInterval(() => {
      idxRef.current++
      if (idxRef.current > text.length) {
        clearInterval(timer)
      }
      setDisplayed(text.slice(0, idxRef.current))
    }, 25)
    return () => clearInterval(timer)
  }, [text, enabled])

  return (
    <>
      {displayed || text.slice(0, 1)}
      <span
        className="inline-block w-0.5 h-4 ml-0.5 align-text-bottom animate-pulse"
        style={{ backgroundColor: 'var(--accent)' }}
      />
    </>
  )
}

// ── 叙事构建 ──────────────────────────────────────────

const AGENT_EMOJI: Record<string, string> = {
  intention: '\u{1F9E0}',       // 🧠
  event_collection: '\u{1F4CB}', // 📋
  preference: '\u{2B50}',        // ⭐
  information_query: '\u{1F50D}', // 🔍
  itinerary_planning: '\u{1F5FA}️', // 🗺️
  memory_query: '\u{1F4BE}',     // 💾
  rag_knowledge: '\u{1F4DA}',   // 📚
  currency_converter: '\u{1F4B1}', // 💱
  currency_conversion: '\u{1F4B1}', // 💱
  expense_tracking: '\u{1F4B0}', // 💰
  translation: '\u{1F310}',      // 🌐
  visa_info: '\u{1FAA2}',       // 🪂
  train_ticket: '\u{1F682}',    // 🚂
}

function buildNarrativeLines(
  intention: IntentionData | null,
  results: AgentResult[],
  running: string[],
): NarrativeLine[] {
  const lines: NarrativeLine[] = []

  // Line 1: 意图理解
  const intentText = intention?.rewritten_query
    ? `理解了：${intention.rewritten_query}`
    : '理解需求中...'
  lines.push({
    id: 'intent',
    agentName: 'intention',
    text: intentText,
    status: intention ? 'done' : 'active',
  })

  if (!intention?.agent_schedule) return lines

  // Lines 2..N: 各 agent
  const completedNames = new Set(results.map((r) => r.agent_name))
  const errorNames = new Set(
    results.filter((r) => r.status === 'error').map((r) => r.agent_name),
  )
  const runningSet = new Set(running)

  for (const agent of intention.agent_schedule) {
    const name = agent.agent_name
    let status: NarrativeLine['status'] = 'pending'
    if (errorNames.has(name)) status = 'error'
    else if (completedNames.has(name)) status = 'done'
    else if (runningSet.has(name)) status = 'active'

    const result = results.find((r) => r.agent_name === name)
    const narrative = makeNarrative(name, result)

    lines.push({
      id: name,
      agentName: name,
      text: narrative,
      status,
      result,
    })
  }

  // Line N+1: 整合完成
  const allDone = intention.agent_schedule.every(
    (a) => completedNames.has(a.agent_name),
  )
  lines.push({
    id: 'complete',
    agentName: 'complete',
    text: '整合结果，为您生成回复...',
    status: allDone ? 'active' : 'pending',
  })

  return lines
}

function makeNarrative(agentName: string, result?: AgentResult): string {
  const emoji = AGENT_EMOJI[agentName] || '\u{1F4CC}' // 📌
  const label = getAgentLabel(agentName)
  const prefix = `${emoji} ${label}`

  if (!result) return `${prefix} 执行中...`

  const d = result.data as Record<string, unknown>
  const inner = (d?.data as Record<string, unknown>) || d || {}

  switch (agentName) {
    case 'event_collection': {
      const dest = (inner.destination || d.destination || '') as string
      const date = (inner.date || inner.start_date || d.date || d.start_date || '') as string
      if (date && dest) return `${prefix}: ${date} → ${dest}`
      if (dest) return `${prefix}: 目的地 ${dest}`
      return `${prefix} 完成`
    }
    case 'preference': {
      const prefs = inner.preferences as { value?: string }[] | undefined
      if (Array.isArray(prefs) && prefs.length > 0) {
        const vals = prefs.map((p) => p.value).filter(Boolean).join('\u{3001}')
        return `${prefix}: ${vals}`
      }
      return `${prefix} 完成`
    }
    case 'information_query': {
      const summary = (inner.summary || d.summary || d.message || d.answer) as string
      if (summary) {
        const s = summary.length > 50 ? summary.slice(0, 50) + '...' : summary
        return `${prefix}: ${s}`
      }
      return `${prefix} 完成`
    }
    case 'itinerary_planning': {
      const itin = (inner.itinerary || d.itinerary) as Record<string, unknown> | undefined
      const title = (itin?.title || d.title || inner.title) as string
      return title ? `${prefix}: ${title}` : `${prefix}: 规划完成`
    }
    case 'currency_converter':
    case 'currency_conversion': {
      const from = (inner.from_amount || d.from_amount) as string
      const to = (inner.to_amount || d.to_amount) as string
      const fc = (inner.from_currency || d.from_currency) as string
      const tc = (inner.to_currency || d.to_currency) as string
      if (from && to) return `${prefix}: ${from} ${fc} = ${to} ${tc}`
      return `${prefix} 完成`
    }
    case 'expense_tracking': {
      const cat = (inner.category || d.category || '') as string
      const amt = (inner.amount || d.amount || '') as string
      if (cat && amt) return `${prefix}: ${cat} ${amt}元`
      if (amt) return `${prefix}: ${amt}元`
      return `${prefix} 完成`
    }
    case 'train_ticket': {
      const count = (inner.train_count || inner.count || d.train_count) as number
      const fastest = (inner.fastest_train || inner.fastest || d.fastest_train) as string
      if (count && fastest) return `${prefix}: 查到${count}趟列车，最快${fastest}`
      if (count) return `${prefix}: 查到${count}趟列车`
      return `${prefix} 完成`
    }
    case 'memory_query':
    case 'rag_knowledge': {
      const answer = (inner.answer || inner.content || inner.result || d.answer) as string
      if (answer) {
        const s = answer.length > 50 ? answer.slice(0, 50) + '...' : answer
        return `${prefix}: ${s}`
      }
      return `${prefix} 完成`
    }
    case 'visa_info':
    case 'translation':
    case 'query_info':
    default: {
      const msg = (inner.summary || inner.message || inner.answer || d.summary || d.message) as string
      if (msg) {
        const s = msg.length > 50 ? msg.slice(0, 50) + '...' : msg
        return `${prefix}: ${s}`
      }
      return `${prefix} 完成`
    }
  }
}
