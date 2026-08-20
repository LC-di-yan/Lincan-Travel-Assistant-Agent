import { useMemo } from 'react'
import { getAgentLabel, getAgentColor } from '../Icons/AgentIcon'
import type { IntentionData, AgentResult } from '../../api/types'

interface FlightMapProps {
  intention: IntentionData | null
  results: AgentResult[]
  running: string[]
}

interface MapNode {
  id: string
  label: string
  color: string
  emoji: string
}

type NodeStatus = 'done' | 'active' | 'pending' | 'error'

const EMOJI: Record<string, string> = {
  start: '\u{1F9E0}',
  event_collection: '\u{1F4CB}',
  preference: '\u{2B50}',
  information_query: '\u{1F50D}',
  itinerary_planning: '\u{1F5FA}',
  memory_query: '\u{1F4BE}',
  rag_knowledge: '\u{1F4DA}',
  currency_converter: '\u{1F4B1}',
  currency_conversion: '\u{1F4B1}',
  expense_tracking: '\u{1F4B8}',
  translation: '\u{1F310}',
  visa_info: '\u{2708}',
  train_ticket: '\u{1F682}',
  end: '\u{2728}',
}

const VW = 800
const VH = 100
const PAD_X = 60
const PAD_Y = 24

export function FlightMap({ intention, results, running }: FlightMapProps) {
  const nodes = useMemo(() => buildNodes(intention), [intention])

  const completedSet = useMemo(() => new Set(results.filter((r) => r.status === 'success').map((r) => r.agent_name)), [results])
  const errorSet = useMemo(() => new Set(results.filter((r) => r.status === 'error').map((r) => r.agent_name)), [results])
  const runningSet = useMemo(() => new Set(running), [running])

  // 每个节点的状态
  const statuses = useMemo(
    () => nodes.map((n) => nodeStatus(n, completedSet, runningSet, errorSet, intention)),
    [nodes, completedSet, runningSet, errorSet, intention],
  )

  // 节点 SVG 坐标
  const points = useMemo(() => {
    if (nodes.length === 1) return [{ x: VW / 2, y: VH / 2 }]
    return nodes.map((_, i) => ({
      x: PAD_X + (i / (nodes.length - 1)) * (VW - 2 * PAD_X),
      y: VH / 2 + (i % 2 === 0 ? -PAD_Y : PAD_Y),
    }))
  }, [nodes.length])

  if (nodes.length === 0) return null

  return (
    <div className="px-3 pt-3 pb-0.5">
      <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto" style={{ maxHeight: 110 }}>
        {/* 连接线 */}
        {points.slice(0, -1).map((p, i) => {
          const seg = segmentStatus(statuses[i], statuses[i + 1])
          return (
            <line
              key={`seg-${i}`}
              x1={p.x} y1={p.y}
              x2={points[i + 1].x} y2={points[i + 1].y}
              stroke={segColor(seg)}
              strokeWidth={seg === 'active' ? 2.5 : 2}
              strokeDasharray={seg === 'done' ? undefined : '6 4'}
              strokeLinecap="round"
              className={seg === 'active' ? 'flight-line-active' : ''}
            />
          )
        })}

        {/* 节点 */}
        {nodes.map((node, i) => {
          const p = points[i]
          const s = statuses[i]
          return <MapNodeSvg key={node.id} node={node} x={p.x} y={p.y} status={s} />
        })}
      </svg>

      <style>{`
        .flight-line-active {
          animation: dash-march 0.6s linear infinite;
        }
        @keyframes dash-march {
          to { stroke-dashoffset: -20; }
        }
      `}</style>
    </div>
  )
}

/* ── 单个地图节点 ── */

function MapNodeSvg({ node, x, y, status }: { node: MapNode; x: number; y: number; status: NodeStatus }) {
  const size = status === 'active' ? 13 : 10
  const fill = status === 'done' ? '#10b981'
    : status === 'active' ? node.color
    : status === 'error' ? '#ef4444'
    : 'transparent'
  const stroke = status === 'pending' ? 'var(--border, #d1d5db)' : 'transparent'

  return (
    <g>
      {/* 脉冲 (active) */}
      {status === 'active' && (
        <circle cx={x} cy={y} r={15} fill="none" stroke={node.color} strokeWidth={1.5} opacity={0.4}>
          <animate attributeName="r" from={12} to={19} dur="1.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" from={0.5} to={0} dur="1.2s" repeatCount="indefinite" />
        </circle>
      )}

      <circle cx={x} cy={y} r={size} fill={fill} stroke={stroke} strokeWidth={2} />

      {status === 'done' ? (
        <text x={x} y={y + 1} textAnchor="middle" dominantBaseline="central" fontSize={11} fill="white" style={{ pointerEvents: 'none' }}>✓</text>
      ) : status === 'error' ? (
        <text x={x} y={y + 1} textAnchor="middle" dominantBaseline="central" fontSize={11} fill="white" style={{ pointerEvents: 'none' }}>!</text>
      ) : (
        <text x={x} y={y + 1} textAnchor="middle" dominantBaseline="central" fontSize={status === 'active' ? 13 : 10} opacity={status === 'pending' ? 0.4 : 1} style={{ pointerEvents: 'none' }}>{node.emoji}</text>
      )}

      <text x={x} y={y + 23} textAnchor="middle" fontSize={9}
        fill={status === 'active' ? node.color : status === 'done' ? '#10b981' : status === 'error' ? '#ef4444' : 'var(--text-muted, #9ca3af)'}
        fontWeight={status === 'active' || status === 'done' ? 600 : 400}
        style={{ pointerEvents: 'none' }}
      >
        {node.label}
      </text>
    </g>
  )
}

/* ── 节点构建 ── */

function buildNodes(intention: IntentionData | null): MapNode[] {
  const nodes: MapNode[] = [
    { id: 'start', label: '理解需求', color: '#8b5cf6', emoji: EMOJI.start },
  ]
  if (intention?.agent_schedule) {
    for (const agent of intention.agent_schedule) {
      nodes.push({
        id: agent.agent_name,
        label: getAgentLabel(agent.agent_name),
        color: getAgentColor(agent.agent_name),
        emoji: EMOJI[agent.agent_name] || '\u{1F4CC}',
      })
    }
  }
  nodes.push({ id: 'end', label: '整合', color: '#10b981', emoji: EMOJI.end })
  return nodes
}

/* ── 状态判定 ── */

function nodeStatus(
  n: MapNode,
  done: Set<string>,
  running: Set<string>,
  err: Set<string>,
  intention: IntentionData | null,
): NodeStatus {
  if (n.id === 'start') {
    return intention ? 'done' : 'active'
  }
  if (n.id === 'end') {
    if (!intention) return 'pending'
    const total = intention.agent_schedule.length
    const finished = done.size + err.size
    return finished >= total ? 'active' : 'pending'
  }
  if (err.has(n.id)) return 'error'
  if (done.has(n.id)) return 'done'
  if (running.has(n.id)) return 'active'
  return 'pending'
}

function segmentStatus(from: NodeStatus, to: NodeStatus): NodeStatus {
  if (from === 'done' && (to === 'done' || to === 'active')) return 'done'
  if ((from === 'done' || from === 'active') && to === 'active') return 'active'
  if (from === 'error' || to === 'error') return 'error'
  if (from === 'done' && to === 'pending') return 'active'
  return 'pending'
}

function segColor(s: NodeStatus): string {
  if (s === 'done') return '#10b981'
  if (s === 'active') return 'var(--accent, #4f8ef7)'
  if (s === 'error') return '#ef4444'
  return 'var(--border, #e5e7eb)'
}
