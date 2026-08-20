import { useState, useEffect } from 'react'
import { FlightMap } from './FlightMap'
import { NarrativeTimeline } from './NarrativeTimeline'
import { JourneyProgress } from './JourneyProgress'
import type { IntentionData, AgentResult } from '../../api/types'

interface ThinkingJourneyProps {
  thinkingStatus: string
  intention: IntentionData | null
  agentResults: AgentResult[]
  runningAgents: string[]
}

export function ThinkingJourney({ thinkingStatus, intention, agentResults, runningAgents }: ThinkingJourneyProps) {
  const [exiting, setExiting] = useState(false)

  // 当全部完成后触发退出动画：所有 running 清空 + 有结果 + thinkingStatus 为空
  const allDone = runningAgents.length === 0 && agentResults.length > 0 && thinkingStatus === ''
  const totalStages = (intention?.agent_schedule?.length ?? 0) + 2
  const completedStages = agentResults.length + (intention ? 1 : 0)

  useEffect(() => {
    if (allDone) {
      // 延迟触发退出，留时间给最后一行打字机播完
      const t = setTimeout(() => setExiting(true), 600)
      return () => clearTimeout(t)
    } else {
      setExiting(false)
    }
  }, [allDone])

  return (
    <div
      className="rounded-2xl overflow-hidden animate-fade-in-up"
      style={{
        border: '1px solid var(--border)',
        backgroundColor: 'var(--bg-elevated)',
        boxShadow: 'var(--shadow-sm)',
        animation: exiting ? 'journey-exit 0.35s ease forwards' : undefined,
      }}
    >
      {/* 标题栏 */}
      <div
        className="flex items-center gap-2 px-4 py-2"
        style={{ backgroundColor: 'var(--bg-secondary)' }}
      >
        <span className="text-xs font-semibold text-[var(--text-primary)]">
          {intention ? '\u{1F9F3} AI 思考手记' : '\u{1F9F3} 分析中...'}
        </span>
        {intention && (
          <span className="text-xs text-[var(--text-muted)]">
            {completedStages}/{totalStages}
          </span>
        )}
      </div>

      {/* 地图 */}
      <FlightMap
        intention={intention}
        results={agentResults}
        running={runningAgents}
      />

      {/* 时间线 */}
      <NarrativeTimeline
        intention={intention}
        results={agentResults}
        running={runningAgents}
      />

      {/* 进度条 */}
      <JourneyProgress total={totalStages} completed={completedStages} />

      <style>{`
        @keyframes journey-exit {
          to {
            opacity: 0;
            transform: translateY(-8px);
            max-height: 0;
            margin-bottom: 0;
          }
        }
      `}</style>
    </div>
  )
}
