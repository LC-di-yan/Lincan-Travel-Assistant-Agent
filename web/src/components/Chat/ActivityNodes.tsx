import { activityStates, type ActivityNode } from '../../utils/agentActivity'

export function ActivityNodes({ nodes }: { nodes: ActivityNode[] }) {
  if (!nodes.length) return null
  return <ul className="activity-nodes" aria-label="任务状态">{nodes.map(node =>
    <li key={node.id} data-state={node.status}>
      <span className="state-mark" aria-hidden="true" />
      <span>{node.label}</span><strong>{activityStates[node.status]}</strong>
    </li>)}</ul>
}
