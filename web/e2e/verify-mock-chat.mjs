import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const URL = process.env.CHAT_URL || 'http://127.0.0.1:8100/'
const PORT = 9390
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const profile = mkdtempSync(join(tmpdir(), 'aligo-mock-'))
const sleep = ms => new Promise(r => setTimeout(r, ms))
const edge = spawn(EDGE, ['--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=1','--remote-debugging-port='+PORT,'--user-data-dir='+profile,'--no-first-run','about:blank'], { stdio: 'ignore' })
async function fp(){for(let i=0;i<50;i++){try{const l=await(await fetch('http://127.0.0.1:'+PORT+'/json/list')).json();const p=l.find(x=>x.type==='page');if(p?.webSocketDebuggerUrl)return p.webSocketDebuggerUrl}catch{}await sleep(300)}throw new Error('CDP')}
const ws = new WebSocket(await fp())
await new Promise(r => ws.addEventListener('open', r, { once: true }))
let id=0; const pend=new Map()
ws.addEventListener('message', e => { const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){pend.get(m.id)(m);pend.delete(m.id)} })
const send=(m,p={})=>{const i=++id;return new Promise(r=>{pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}))})}
const ev=async x=>{const r=await send('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});return r.result?.result?.value}
await send('Page.enable'); await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false})
await send('Page.navigate',{url:URL})
for (let i=0;i<40;i++){ await sleep(800); if (await ev('!!document.querySelector("textarea")')) { console.log('SPA ready after', i+1, 'probes'); break } }
await ev("document.documentElement.classList.remove('dark'); true")
await sleep(600)
console.log('scenes nav:', await ev('document.body.innerText.includes("新对话") || !!document.querySelector("textarea")'))

async function ask(text, waitMs) {
  await ev('(function(){var ta=document.querySelector("textarea");var s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set;s.call(ta,' + JSON.stringify(text) + ');ta.dispatchEvent(new Event("input",{bubbles:true}));return 1})()')
  await sleep(400)
  for (let i=0;i<40;i++){ const ok = await ev('(function(){var b=[].slice.call(document.querySelectorAll("button")).filter(function(x){return x.getAttribute("aria-label")==="发送消息"&&!x.disabled})[0];if(b){b.click();return true}return false})()'); if (ok) break; await sleep(250) }
  await sleep(waitMs || 6000)
  const txt = await ev('document.body.innerText')
  return String(txt || '').replace(/\s+/g,' ');
}

const t1 = await ask('100 美元等于多少人民币', 7000)
console.log('Q1 answered:', t1.includes('667.13') || t1.includes('汇率'))
console.log('Q1 snippet:', t1.slice(-160))
const s1 = await send('Page.captureScreenshot',{format:'png'}); writeFileSync('data/mock-chat-1.png', Buffer.from(s1.result.data,'base64'))

const t2 = await ask('北京到上海的高铁票', 7000)
console.log('Q2 answered:', t2.includes('G7') || t2.includes('车次') || t2.includes('余票'))
const s2 = await send('Page.captureScreenshot',{format:'png'}); writeFileSync('data/mock-chat-2.png', Buffer.from(s2.result.data,'base64'))

const t3 = await ask('今天天气真好呀呀呀', 6000)
console.log('Q3 fallback:', t3.includes('静态演示') || t3.includes('覆盖'))
ws.close(); edge.kill(); process.exit(0)