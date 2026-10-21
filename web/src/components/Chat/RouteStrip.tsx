import { useEffect, useMemo, useState } from 'react'
import { Square } from 'lucide-react'
import type { AgentResult, IntentionData } from '../../api/types'
import { getAgentLabel } from '../Icons/AgentIcon'

type NodeStatus = 'pending' | 'active' | 'done' | 'error'

interface Node {
  id: string
  label: string
  status: NodeStatus
}

export function RouteStrip({
  intention,
  results,
  running,
  onCancel,
}: {
  intention: IntentionData | null
  results: AgentResult[]
  running: string[]
  onCancel: () => void
}) {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const nodes = useMemo<Node[]>(() => {
    const list: Node[] = [{ id: 'intent', label: '理解', status: intention ? 'done' : 'active' }]
    const schedule = intention?.agent_schedule ?? []

    for (const item of schedule) {
      const name = item.agent_name
      const result = results.find((r) => r.agent_name === name)
      const status: NodeStatus = result
        ? result.status === 'error' ? 'error' : 'done'
        : running.includes(name) ? 'active' : 'pending'
      list.push({ id: name, label: getAgentLabel(name), status })
    }

    if (schedule.length === 0) {
      list.push({
        id: 'work',
        label: '查询与规划',
        status: intention ? 'active' : 'pending',
      })
    }

    const allDone = schedule.length > 0 && schedule.every((a) =>
      results.some((r) => r.agent_name === a.agent_name),
    )
    list.push({ id: 'summary', label: '汇总', status: allDone ? 'active' : 'pending' })
    return list
  }, [intention, results, running])

  const active = nodes.find((n) => n.status === 'active')
  const done = nodes.filter((n) => n.status === 'done').length

  return (
    <div className="w-full rounded-[2px] border border-rule bg-paper-raised" aria-label="处理进度">
      <div className="flex items-center justify-between border-b border-rule px-4 py-2">
        <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.12em] text-ink-3">
          <span className="text-accent">ALIGO / 处理中</span>
          <span className="tabular">{done}/{nodes.length}</span>
          <span className="tabular">{seconds}s</span>
        </div>
        <button
          type="button"
          onClick={onCancel}
          className="flex h-9 items-center gap-1.5 rounded-[2px] border border-rule-strong px-2.5 text-[11px] font-medium text-ink-2 hover:bg-paper-sunken"
        >
          <Square size={10} fill="currentColor" aria-hidden="true" />
          停止
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-2 px-4 py-3">
        {nodes.map((node, i) => (
          <div key={node.id} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`h-1.5 w-1.5 rounded-full ${
                node.status === 'done'
                  ? 'bg-ok'
                  : node.status === 'active'
                    ? 'bg-accent ring-4 ring-accent/10'
                    : node.status === 'error'
                      ? 'bg-err'
                      : 'border border-rule-strong bg-transparent'
              }`}
            />
            <span
              className={`text-[11px] ${
                node.status === 'active'
                  ? 'font-semibold text-ink'
                  : node.status === 'error'
                    ? 'text-err'
                    : node.status === 'pending'
                      ? 'text-ink-3'
                      : 'text-ink-2'
              }`}
            >
              {node.label}
            </span>
            {i < nodes.length - 1 && (
              <span
                aria-hidden="true"
                className={`ml-1 h-px w-4 ${node.status === 'done' ? 'bg-ok/50' : 'bg-rule'}`}
              />
            )}
          </div>
        ))}
      </div>

      <p className="sr-only" aria-live="polite">
        {active ? '正在' + active.label : '正在汇总结果'}
      </p>
    </div>
  )
}
