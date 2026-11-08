import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const URL = process.env.DEMO_URL || 'http://127.0.0.1:8099/'
const TAG = process.env.SHOT_TAG || 'gp-demo'
const PORT = 9381
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const profile = mkdtempSync(join(tmpdir(), 'aligo-gpdemo-'))
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
await send('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false})
await send('Page.navigate',{url:URL})
await sleep(3500)
const shot = async n => { const r = await send('Page.captureScreenshot',{format:'png'}); writeFileSync('data/'+TAG+'-'+n+'.png', Buffer.from(r.result.data,'base64')); return n }
console.log('scenes:', await ev('document.querySelectorAll(".scene").length'))
console.log('answer:', (await ev('document.getElementById("ans").textContent'))?.slice(0,60))
console.log('card:', await ev('!!document.querySelector(".card")'))
console.log('shot1:', await shot('gp-demo-1'))
// 切到汇率场景
await ev('document.querySelectorAll(".scene")[5].click()')
await sleep(1500)
console.log('fx card text:', (await ev('document.querySelector(".card")?.innerText'))?.replace(/\s+/g,' ').slice(0,80))
console.log('shot2:', await shot('gp-demo-2'))
ws.close(); edge.kill(); process.exit(0)