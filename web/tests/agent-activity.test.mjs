import test from 'node:test'
import assert from 'node:assert/strict'
import { projectAgentActivity } from '../src/utils/agentActivity.ts'

const node = (id, label) => ({ agent_name: 'train_ticket', node_id: id, label })
const out = node('outbound', '去程')
const back = node('inbound', '返程')
const initial = { phase: 'receiving', schedule: [out, back], running: [], results: [] }
const view = args => projectAgentActivity({ ...initial, ...args })
const statuses = args => view(args).nodes.map(n => n.status)

test('同名去返程按节点区分，计划不等于已启动，部分结果不等于完成', () => {
  assert.deepEqual(statuses({ running: [out] }), ['running', 'pending'])
  assert.deepEqual(statuses({ running: [back], results: [{ ...out, status: 'success', node_status: 'partial' }] }),
    ['partial', 'running'])
})

test('先收到结果、无调度、缓存与完整快照按公开事实呈现', () => {
  const results = [{ ...out, status: 'success', cached: true }, { ...back, status: 'error', node_status: 'timeout' }]
  assert.deepEqual(statuses({ phase: 'finished', schedule: [], results }), ['cached', 'timeout'])
  assert.deepEqual(statuses({ schedule: [], running: [out] }), ['running'])
  for (const status of ['failed', 'partial', 'unavailable', 'skipped', 'timeout']) {
    assert.equal(view({ results: [{ ...out, node_status: status, status: 'success' }] }).nodes[0].status, status)
  }
})

test('停止、澄清、断线及缺失的终态不虚报任务成功', () => {
  const settled = { ...out, status: 'success' }
  assert.deepEqual(statuses({ phase: 'cancelled', results: [settled], running: [back] }), ['success', 'stopped'])
  assert.deepEqual(statuses({ phase: 'error', running: [out] }), ['unreported', 'unreported'])
  assert.match(view({ phase: 'clarification' }).summary, /补充/)
  assert.equal(view({ phase: 'finished', schedule: [] }).nodes.length, 0)
  assert.match(view({ phase: 'finished', finalStatus: 'partial_failure' }).summary, /待核验/)
  assert.match(view({ phase: 'submitted', schedule: [] }).summary, /等待响应/)
})

test('匿名重复任务不捏造独立进度，投影不包含私有字段或未识别的内部名', () => {
  const task = { agent_name: 'opaque_internal_tool', reason: 'PRIVATE', expected_output: 'PRIVATE' }
  const projection = view({ schedule: [task, task], results: [{ ...task, status: 'success', data: { reasoning: 'PRIVATE' } }] })
  assert.equal(projection.nodes.length, 1)
  assert.equal(projection.nodes[0].label, '其他任务（同类任务）')
  assert.equal(projection.nodes[0].status, 'returned')
  assert.doesNotMatch(JSON.stringify(projection), /PRIVATE/)
})

test('终场快照覆盖同节点的中间状态，但不会抹掉已收到的其他节点', () => {
  assert.deepEqual(statuses({ phase: 'finished', results: [
    { ...out, status: 'success', node_status: 'partial' }, { ...back, status: 'success', cached: true }],
    finalResults: [{ ...out, status: 'error', node_status: 'unavailable' }] }), ['unavailable', 'cached'])
  assert.deepEqual(statuses({ phase: 'cancelled', schedule: [], running: [back] }), ['stopped'])
  assert.deepEqual(statuses({ phase: 'finished', finalSchedule: [] }), ['unreported', 'unreported'])
})

test('未识别的详细状态不会被上层 success 涂成已完成，节点取消也不是失败', () => {
  assert.deepEqual(statuses({ results: [
    { ...out, status: 'success', node_status: 'new_contract_value' },
    { ...back, status: 'error', node_status: 'cancelled' },
  ] }), ['returned', 'stopped'])
})

test('知识库未找到条款或索引不可用时不显示已完成', () => {
  const knowledge = { agent_name: 'rag_knowledge' }
  for (const [status, knowledgeStatus, projected] of [['success', 'no_knowledge', 'no_match'], ['error', 'unavailable', 'unavailable']]) {
    const result = view({ phase: 'finished', schedule: [knowledge],
      results: [{ ...knowledge, status, data: { status: knowledgeStatus } }] })
    assert.equal(result.nodes[0].status, projected)
    assert.match(result.summary, /待核验/)
  }
})
