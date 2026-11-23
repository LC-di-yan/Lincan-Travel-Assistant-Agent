import type { AgentResult, Message, PublicAgent } from '../api/types'
import { AGENT_CONFIG } from '../components/Icons/agentConfig.ts'
import { unwrapResultData } from './resultData.ts'

// Only public scheduling facts and allowlisted receipt states belong in this projection.
export type RunPhase = 'idle' | 'submitted' | 'receiving' | 'finished' | 'clarification' | 'error' | 'cancelled' | 'interrupted' | 'archived'
export const activityStates = {
  pending: '待开始', running: '进行中', success: '已完成', cached: '已复用', partial: '部分完成',
  failed: '失败', timeout: '超时', unavailable: '无可核验数据', skipped: '已跳过',
  stopped: '已停止', unreported: '未收到结果', returned: '已收到结果', awaiting: '待确认',
} as const
type NodeState = keyof typeof activityStates
export interface TurnActivity { phase: RunPhase; schedule: PublicAgent[]; started: PublicAgent[] }

export function publicTask(row: PublicAgent): PublicAgent {
  return { agent_name: row.agent_name, node_id: row.node_id, label: row.label,
    depends_on: Array.isArray(row.depends_on) ? row.depends_on.filter(id => typeof id === 'string') : undefined }
}
type Identity = PublicAgent
type ResultFact = Identity & Pick<AgentResult, 'status' | 'node_status' | 'cached'> & { data?: unknown }

export interface ActivityNode {
  id: string
  label: string
  status: NodeState
}
interface Facts {
  phase: RunPhase
  schedule: readonly Identity[]
  finalSchedule?: readonly Identity[]
  running: readonly Identity[]
  results: readonly ResultFact[]
  finalResults?: readonly ResultFact[]
  finalStatus?: string
}

const keyOf = (row: Identity) => row.node_id || row.agent_name
const labelOf = (row: Identity) => (typeof row.label === 'string' && row.label.trim()) || (Object.hasOwn(AGENT_CONFIG, row.agent_name)
  ? AGENT_CONFIG[row.agent_name].label : '其他任务')

function reconcile<T extends Identity>(observed: readonly T[], snapshot?: readonly T[]) {
  if (!snapshot) return observed
  const keys = new Set(snapshot.map(keyOf))
  return [...observed.filter(row => !keys.has(keyOf(row))), ...snapshot]
}

// A shorter dispatch/final packet can refine a task without repeating its parents.
export function mergeSchedule(previous: readonly Identity[], next: readonly Identity[]) {
  const rows = [...previous]
  const counts = new Map<string, number>()
  for (const item of next) {
    const id = item.node_id
    const n = counts.get(item.agent_name) ?? 0
    if (!id) counts.set(item.agent_name, n + 1)
    let i = 0
    const index = rows.findIndex(row => id ? row.node_id === id :
      !row.node_id && row.agent_name === item.agent_name && i++ === n)
    if (index < 0) rows.push(item)
    else rows[index] = { ...rows[index], ...item, label: item.label ?? rows[index].label,
      depends_on: item.depends_on ?? rows[index].depends_on }
  }
  return rows
}

function resultState(row: ResultFact): NodeState {
  if (row.status === 'success' && (!row.node_status || row.node_status === 'success') &&
      ['expense_tracker', 'expense_tracking'].includes(row.agent_name)) {
    const action = unwrapResultData(row.data).action
    if (action === 'preview') return 'awaiting'
    if (action === 'error' || action === 'unknown') return 'failed'
  }
  if (row.node_status === 'success') return row.cached ? 'cached' : 'success'
  if (row.node_status === 'cancelled') return 'stopped'
  if (row.node_status) return Object.hasOwn(activityStates, row.node_status) ? row.node_status : 'returned'
  if (row.status === 'success') return row.cached ? 'cached' : 'success'
  return row.status === 'error' ? 'failed' : 'returned'
}

export function projectAgentActivity({ phase, schedule, finalSchedule, running, results, finalResults, finalStatus }: Facts) {
  const live = phase === 'submitted' || phase === 'receiving'
  const cancelled = phase === 'cancelled' || finalStatus === 'cancelled'
  const nodes = new Map<string, ActivityNode>()
  const duplicates = new Set<string>()
  const reported = new Map<string, NodeState>()
  const declared = finalSchedule ? mergeSchedule(schedule, finalSchedule) : schedule
  for (const row of declared) {
    const id = keyOf(row)
    if (!id) continue
    if (!row.node_id && nodes.has(id)) duplicates.add(id)
    nodes.set(id, { id, label: labelOf(row), status: live ? 'pending' : cancelled ? 'stopped' : 'unreported' })
  }
  const ids = new Set(declared.map(row => row.node_id).filter(Boolean))
  const edges = declared.flatMap(row => row.node_id && Array.isArray(row.depends_on)
    ? [...new Set(row.depends_on)].filter(parent => parent !== row.node_id && ids.has(parent))
        .map(from => ({ from, to: row.node_id! })) : [])
  const started = new Set<string>()
  for (const row of running) {
    const id = keyOf(row)
    if (!id) continue
    if (!row.node_id && started.has(id)) duplicates.add(id)
    started.add(id)
    const node = nodes.get(id) ?? { id, label: labelOf(row), status: 'pending' }
    nodes.set(id, { ...node, status: live ? 'running' : cancelled ? 'stopped' : 'unreported' })
  }
  for (const row of reconcile(results, finalResults)) {
    const id = keyOf(row)
    if (!id) continue
    let status = resultState(row)
    const prior = reported.get(id)
    if (!row.node_id && prior) {
      duplicates.add(id)
      // Anonymous invocations cannot overwrite a different invocation's failure with success.
      if (prior !== status) status = 'partial'
    }
    reported.set(id, status)
    if (status === 'running') {
      if (!live) status = cancelled ? 'stopped' : 'unreported'
      else if (!started.has(id)) status = 'pending'
    }
    if (duplicates.has(id) && (status === 'success' || status === 'cached')) status = 'returned'
    nodes.set(id, { id, label: status === 'awaiting' ? '费用预览' : nodes.get(id)?.label ?? labelOf(row), status })
  }
  const list = [...nodes.values()].map(n => duplicates.has(n.id) ? { ...n, label: n.label + '（同类任务）' } : n)
  const active = list.filter(n => n.status === 'running')
  const hasIssues = list.some(n => ['failed', 'partial', 'timeout', 'unavailable', 'skipped', 'stopped', 'unreported', 'returned'].includes(n.status))
  let summary: string
  if (cancelled) summary = '本轮已停止'
  else if (phase === 'interrupted') summary = '连接中断，未收到完整回复'
  else if (phase === 'archived') summary = '历史记录 · 未保存完整过程'
  else if (phase === 'error' || finalStatus === 'failed') summary = '本轮未能完成'
  else if (phase === 'clarification') summary = '等待你补充信息'
  else if (phase === 'finished') summary = hasIssues || finalStatus === 'partial_failure' ? '本轮结束，有待核验项' : '本轮已结束'
  else if (phase === 'idle') summary = '尚无进行中的任务'
  else if (active.length) summary = '正在处理：' + active.map(n => n.label).join('、')
  else if (results.length) summary = '已收到结果，等待本轮结束'
  else if (list.length) summary = '任务已列出，等待开始'
  else summary = phase === 'submitted' ? '已提交，等待响应' : '正在解析需求'
  const returned = [...reported.values()].filter(status => status !== 'running').length
  const graphEligible = edges.length > 0 && ids.size === list.length && ids.size === declared.length &&
    declared.every(n => Array.isArray(n.depends_on ?? []) && (n.depends_on ?? []).every(id => id !== n.node_id && ids.has(id)))
  return { nodes: list, edges, graphEligible, summary, returned, phase, live, started: [...started] }
}

export type ActivityView = ReturnType<typeof projectAgentActivity>
export function messageActivity(msg?: Message): ActivityView {
  const run = msg?.activity
  const view = projectAgentActivity({ phase: run?.phase ?? 'idle', running: run?.started ?? [],
    schedule: run?.schedule ?? [], finalSchedule: msg?.orchestrationResult?.intention?.agent_schedule,
    results: msg?.agentResults ?? [], finalStatus: msg?.orchestrationResult?.status })
  if (msg?.selectionReceipt && view.phase === 'finished') return { ...view, summary: '已确认选择方案 '+msg.selectionReceipt.number+'，未执行预订' }
  return msg?.historical && view.phase === 'interrupted' ? { ...view, summary: '历史回合未完整结束' } : view
}

// Named nodes update in place; legacy repeats have no stable identity. Match their
// occurrence within the final snapshot, never conflate two anonymous live results.
export function mergeResults(previous: readonly AgentResult[], incoming: readonly AgentResult[], final = false) {
  const rows = [...previous]
  const seen = new Map<string, number>()
  for (const row of incoming) {
    let index = -1
    if (row.node_id) index = rows.findIndex(r => r.node_id === row.node_id)
    else if (final) {
      const nth = seen.get(row.agent_name) ?? 0
      let n = 0
      index = rows.findIndex(r => !r.node_id && r.agent_name === row.agent_name && n++ === nth)
      seen.set(row.agent_name, nth + 1)
    }
    if (index < 0) rows.push(row)
    else rows[index] = row
  }
  return rows
}
