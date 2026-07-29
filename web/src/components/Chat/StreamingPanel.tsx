import { useState, useEffect, useRef } from 'react'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { AgentIcon, getAgentLabel } from '../Icons/AgentIcon'
import type { AgentResult } from '../../api/types'

interface StreamingPanelProps {
  results: AgentResult[]
  isRunning: boolean
}

export function StreamingPanel({ results, isRunning }: StreamingPanelProps) {
  const [collapsed, setCollapsed] = useState(false)
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // isRunning 从 true 变为 false 时，延迟 1 秒自动收拢
  useEffect(() => {
    if (!isRunning && results.length > 0) {
      collapseTimerRef.current = setTimeout(() => setCollapsed(true), 1000)
    }
    return () => {
      if (collapseTimerRef.current) clearTimeout(collapseTimerRef.current)
    }
  }, [isRunning, results.length])

  // 新结果到达时，如果已收拢则展开
  useEffect(() => {
    if (results.length > 0 && collapsed && isRunning) {
      setCollapsed(false)
    }
  }, [results.length]) // eslint-disable-line react-hooks/exhaustive-deps

  if (results.length === 0 && !isRunning) return null

  const errorCount = results.filter((r) => r.status === 'error').length

  return (
    <div
      className="rounded-2xl overflow-hidden animate-fade-in-up"
      style={{
        border: '1px solid var(--border)',
        backgroundColor: 'var(--bg-elevated)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      {/* 头部 */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-2.5 transition-colors"
        style={{ backgroundColor: 'var(--bg-secondary)' }}
      >
        <span className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
          {isRunning ? (
            <Loader2 size={14} className="animate-spin text-[var(--accent)]" />
          ) : (
            <span className="text-green-500">✓</span>
          )}
          {isRunning ? '思考过程' : `已完成 ${results.length} 个任务`}
        </span>
        <span className="flex items-center gap-2">
          {!isRunning && errorCount > 0 && (
            <span className="text-xs text-red-400">{errorCount} 个失败</span>
          )}
          {collapsed ? (
            <ChevronRight size={14} className="text-[var(--text-muted)]" />
          ) : (
            <ChevronDown size={14} className="text-[var(--text-muted)]" />
          )}
        </span>
      </button>

      {/* 内容 */}
      {!collapsed && (
        <div className="px-4 py-2.5 space-y-2">
          {results.map((result, i) => (
            <StreamingItem key={result.agent_name + i} result={result} />
          ))}
          {isRunning && results.length === 0 && (
            <div className="text-xs text-[var(--text-muted)] py-1">正在分析...</div>
          )}
        </div>
      )}
    </div>
  )
}

function StreamingItem({ result }: { result: AgentResult }) {
  const { agent_name, status, data } = result
  const label = getAgentLabel(agent_name)
  const isError = status === 'error'

  // 提取摘要文字
  const summary = extractSummary(agent_name, data)

  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="mt-0.5 flex-shrink-0">
        {isError ? (
          <span className="text-red-400">✗</span>
        ) : (
          <span className="text-green-500">✓</span>
        )}
      </span>
      <span className="flex items-center gap-1.5 min-w-0">
        <AgentIcon agentName={agent_name} size={14} />
        <span className="font-medium text-[var(--text-primary)]">{label}</span>
        {summary && (
          <span className="text-[var(--text-muted)] truncate">→ {summary}</span>
        )}
        {isError && (
          <span className="text-red-400 truncate">
            {typeof data.error === 'string' ? data.error : '执行失败'}
          </span>
        )}
      </span>
    </div>
  )
}

function extractSummary(agentName: string, data: Record<string, unknown>): string {
  const d = (data?.data as Record<string, unknown>) || data || {}

  switch (agentName) {
    case 'event_collection': {
      const dest = (d.destination as string) || ''
      const origin = (d.origin as string) || ''
      return dest ? `${origin || '?'} → ${dest}` : ''
    }
    case 'preference': {
      const prefs = d.preferences as { value?: string }[] | undefined
      if (Array.isArray(prefs) && prefs.length > 0) {
        return prefs.map((p) => p.value).filter(Boolean).join(', ')
      }
      return ''
    }
    case 'information_query': {
      const results = d.results as Record<string, unknown> | undefined
      const summary = (results?.summary || d.summary || d.message) as string
      return summary ? summary.slice(0, 40) + (summary.length > 40 ? '...' : '') : ''
    }
    case 'rag_knowledge':
    case 'memory_query': {
      const answer = (d.answer || d.result || d.content) as string
      return answer ? answer.slice(0, 40) + (answer.length > 40 ? '...' : '') : ''
    }
    case 'itinerary_planning': {
      const itin = d.itinerary as Record<string, unknown> | undefined
      const title = (itin?.title || d.title) as string
      return title || '行程已生成'
    }
    default:
      return ''
  }
}
