import test from 'node:test'
import assert from 'node:assert/strict'
import { projectAgentActivity, mergeResults, messageActivity, publicTask } from '../src/utils/agentActivity.ts'
import { selectionSource } from '../src/utils/selectionReceipt.ts'
import { layoutActivity } from '../src/utils/activityGraph.ts'
const task = (id, depends_on=[]) => ({agent_name:'train_ticket',node_id:id,label:id,depends_on})
const row = (id, value, node_status='success')=>({...task(id),node_status,status:'success',data:{value}})
const facts = {phase:'receiving',schedule:[task('去'),task('返'),task('酒店'),task('天气'),task('通勤',['酒店']),task('比较',['去','返','酒店','通勤'])],
 running:[task('酒店')],results:[row('去',1,'partial'),{...row('返',2),cached:true}]}
test('航线只使用已公开的真实依赖；天气不阻塞比较，部分与缓存计入已返回而不是全成功',()=>{
 const view=projectAgentActivity(facts), graph=layoutActivity(view)
 assert.equal(view.returned,2); assert.equal(graph.columns,3)
 assert.deepEqual(graph.paths.map(e=>[e.from,e.to]),[['酒店','通勤'],['去','比较'],['返','比较'],['酒店','比较'],['通勤','比较']])
 assert.deepEqual(view.nodes.map(n=>n.status),['partial','cached','running','pending','pending','pending'])
})
test('无稳定标识、孤立引用、自环、循环依赖和过宽图形回退为同一份任务清单',()=>{
 for(const schedule of [[],[{agent_name:'x'}],[task('a',['b'])],[task('a',['a'])],
    [task('a',['b']),task('b',['a'])],Array.from({length:15},(_,i)=>task(String(i),i?['0']:[]))]){
  const view=projectAgentActivity({...facts,schedule,running:[],results:[]})
  assert.equal(layoutActivity(view),null);assert.equal(view.nodes.length,schedule.length)
 }
})
test('同节点回写、反序快照和只返回部分的终场包保持卡片位置与早到证据',()=>{
 const early=mergeResults([], [row('去',1),row('返',2),row('去',3,'partial')])
 const final=mergeResults(early,[row('返',4),row('酒店',5)],true)
 assert.deepEqual(final.map(r=>[r.node_id,r.data.value]),[['去',3],['返',4],['酒店',5]])
 const legacy=v=>({agent_name:'old',status:'success',data:{value:v}})
 assert.deepEqual(mergeResults([legacy(1),legacy(2)],[legacy(3)],true).map(r=>r.data.value),[3,2])
})
test('每轮独立，历史只读，静态读回不推测未记录过程',()=>{
 const past={activity:{phase:'interrupted',schedule:facts.schedule,started:facts.running},agentResults:facts.results}
 const now={activity:{phase:'submitted',schedule:[],started:[]}}
 assert.equal(messageActivity(now).nodes.length,0)
 assert.equal(messageActivity(past).nodes[2].status,'unreported')
 assert.equal(messageActivity(past).summary,'连接中断，未收到完整回复')
 assert.equal(messageActivity({activity:{...now.activity,phase:'archived'}}).summary,'历史记录 · 未保存完整过程')
 assert.doesNotMatch(JSON.stringify(publicTask({...task('节点'),reason:'PRIVATE',data:{query:'PRIVATE'}})),/PRIVATE/)
})

test('选择回执不能借用其他会话、历史、过期或未经验证的候选',()=>{
 const candidate={id:'original',role:'assistant',orchestrationResult:{candidate_session_id:'trip-a',trip_plan:{
   alternatives:[{id:'A',status:'partial'},{id:'B',status:'validated'}]}}}
 assert.equal(selectionSource(candidate,'选择方案1','trip-a'),undefined)
 assert.equal(selectionSource(candidate,'选择方案2','trip-b'),undefined)
 assert.equal(selectionSource({...candidate,historical:true},'选择方案2','trip-a'),undefined)
 assert.equal(selectionSource(candidate,'预览 B','trip-a'),undefined)
 assert.deepEqual(selectionSource(candidate,'采用第二个方案','trip-a'),{sourceMessageId:'original',optionId:'B',number:2,session:'trip-a'})
})
test('不完整的终场调度不能擦掉已经公开的依赖',()=>{
 const view=projectAgentActivity({...facts,finalSchedule:[{agent_name:'train_ticket',node_id:'通勤'}]})
 assert.ok(view.edges.find(e=>e.from==='酒店' && e.to==='通勤'))
 assert.equal(view.graphEligible,true)
})

test('中间结果不补演未观测到的启动',()=>{
 const queued=task('未知启动')
 const v=projectAgentActivity({phase:'receiving',schedule:[queued],running:[],results:[row('未知启动',0,'running')]})
 assert.equal(v.nodes[0].status,'pending');assert.equal(v.returned,0)
})

test('执行返回的费用预览在协作清单里仍待确认，拒绝不算已完成',()=>{
 const base={phase:'finished',schedule:[{agent_name:'expense_tracking',node_id:'ledger'}],running:[]}
 const result=(action)=>({agent_name:'expense_tracking',node_id:'ledger',status:'success',data:{data:{action,confirmation_command:'PRIVATE'}}})
 const preview=projectAgentActivity({...base,results:[result('preview')]})
 assert.deepEqual(preview.nodes,[{id:'ledger',label:'费用预览',status:'awaiting'}])
 assert.doesNotMatch(JSON.stringify(preview),/PRIVATE/)
 assert.equal(projectAgentActivity({...base,results:[result('error')]}).nodes[0].status,'failed')
 assert.equal(projectAgentActivity({...base,results:[result('record')]}).nodes[0].status,'success')
})
