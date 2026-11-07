// 前端效果演示：多场景截图（Edge + CDP）
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE='http://127.0.0.1:3003', PORT=9350
const EDGE='C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const profile=mkdtempSync(join(tmpdir(),'aligo-demo-'))
const sleep=ms=>new Promise(r=>setTimeout(r,ms))
mkdirSync('data/demo',{recursive:true})
const edge=spawn(EDGE,['--headless=new','--disable-gpu','--hide-scrollbars','--remote-debugging-port='+PORT,'--user-data-dir='+profile,'--no-first-run','about:blank'],{stdio:'ignore'})
async function findPage(){for(let i=0;i<40;i++){try{const l=await(await fetch('http://127.0.0.1:'+PORT+'/json/list')).json();const p=l.find(x=>x.type==='page');if(p?.webSocketDebuggerUrl)return p.webSocketDebuggerUrl}catch{}await sleep(300)}throw new Error('CDP timeout')}
const ws=new WebSocket(await findPage())
await new Promise(r=>ws.addEventListener('open',r,{once:true}))
let id=0;const pend=new Map()
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&pend.has(m.id)){pend.get(m.id)(m);pend.delete(m.id)}})
const send=(method,params={})=>{const i=++id;return new Promise(r=>{pend.set(i,r);ws.send(JSON.stringify({id:i,method,params}))})}
const ev=async x=>{const r=await send('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});return r.result?.result?.value}
const shot=async n=>{const r=await send('Page.captureScreenshot',{format:'png'});writeFileSync('data/demo/'+n+'.png',Buffer.from(r.result.data,'base64'));return n+'.png'}
async function ask(text,wait){
  await ev(`(()=>{const ta=document.querySelector('textarea');const s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;s.call(ta,${JSON.stringify(text)});ta.dispatchEvent(new Event('input',{bubbles:true}));return 1})()`)
  await sleep(350)
  // 等发送按钮真正可用：上一轮仍在生成时渲染的是「停止生成」，
  // 直接找发送按钮会静默点空，导致该条查询根本没发出去。
  const sent = await ev(`(async()=>{for(let i=0;i<60;i++){const b=[...document.querySelectorAll('button')].find(x=>x.getAttribute('aria-label')==='发送消息'&&!x.disabled);if(b){b.click();return 'sent'}await new Promise(r=>setTimeout(r,300))}return 'never enabled'})()`)
  if (sent !== 'sent') console.log('  WARN send:', sent)
  await sleep(wait)
}

await send('Page.enable');await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false})
await send('Page.navigate',{url:BASE});await sleep(3500)
await ev(`document.documentElement.classList.remove('dark');true`);await sleep(600)
console.log('01 空状态(浅色):',await shot('01-empty-light'))

await ask('记一笔打车费 50 元',13000)
console.log('02 费用卡(新图标):',await shot('02-expense-card'))

await ask('我喜欢住万豪，座位要靠窗，请记住',13000)
console.log('03 偏好卡(新图标):',await shot('03-preference-card'))

await ask('100 美元等于多少人民币',16000)
console.log('04 汇率卡(ISO代码芯片):',await shot('04-currency-card'))

// 侧栏费用面板
await ev(`(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='费用');if(b){b.click();return 'opened'}return 'not found'})()`)
await sleep(2500)
console.log('05 侧栏费用面板:',await shot('05-sidebar-expense'))

console.log('DOM probe:',await ev(`JSON.stringify({svg:document.querySelectorAll('svg').length,emoji:(document.body.innerText.match(/[\\u{1F300}-\\u{1FAFF}\\u{2600}-\\u{27BF}]/gu)||[]).length,alerts:document.querySelectorAll('[role=alert]').length,log:!!document.querySelector('[role=log][aria-live]')})`))

// 深色
await ev(`document.documentElement.classList.add('dark');true`);await sleep(700)
console.log('06 深色全貌:',await shot('06-dark-overview'))

// 移动端
await ev(`document.documentElement.classList.remove('dark');true`)
await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true})
await send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:5})
await sleep(1200)
console.log('07 移动端:',await shot('07-mobile'))
ws.close();edge.kill();process.exit(0)