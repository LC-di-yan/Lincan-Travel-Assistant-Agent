import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const URL = 'https://844b3e816654c3.lhr.life'
const PORT = 9370
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const profile = mkdtempSync(join(tmpdir(), 'aligo-tunnel-'))
const sleep = ms => new Promise(r => setTimeout(r, ms))
const edge = spawn(EDGE, ['--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=1','--remote-debugging-port='+PORT,'--user-data-dir='+profile,'--no-first-run','about:blank'], { stdio: 'ignore' })
async function fp(){for(let i=0;i<60;i++){try{const l=await(await fetch('http://127.0.0.1:'+PORT+'/json/list')).json();const p=l.find(x=>x.type==='page');if(p?.webSocketDebuggerUrl)return p.webSocketDebuggerUrl}catch{}await sleep(300)}throw new Error('CDP')}
const ws = new WebSocket(await fp())
await new Promise(r => ws.addEventListener('open', r, { once: true }))
let id=0; const pend=new Map()
ws.addEventListener('message', e => { const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){pend.get(m.id)(m);pend.delete(m.id)} })
const send=(m,p={})=>{const i=++id;return new Promise(r=>{pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}))})}
const ev=async x=>{const r=await send('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});return r.result?.result?.value}
await send('Page.enable'); await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false})
await send('Page.navigate',{url:URL})
// 公网首屏比本地慢，轮询等待 SPA 挂载完成再操作
for (let i = 0; i < 60; i++) {
  await sleep(1000)
  const ready = await ev('!!document.querySelector("textarea")')
  if (ready) { console.log('SPA ready after', i + 1, 's'); break }
}
await sleep(1500)
await ev("document.documentElement.classList.remove('dark'); true")
await sleep(700)
const title = await ev('document.title')
const hasInput = await ev('!!document.querySelector("textarea")')
console.log('title:', title, '| textarea:', hasInput)
// 发一条真实请求
await ev('(function(){var ta=document.querySelector("textarea");var s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set;s.call(ta,"100 美元等于多少人民币");ta.dispatchEvent(new Event("input",{bubbles:true}));return 1})()')
await sleep(600)
for (let i=0;i<60;i++){ if (await ev('(function(){var b=[].slice.call(document.querySelectorAll("button")).filter(function(x){return x.getAttribute("aria-label")==="发送消息"&&!x.disabled})[0];if(b){b.click();return true}return false})()')) break; await sleep(300) }
const dl = Date.now() + 90000
while (Date.now() < dl) {
  await sleep(2000)
  const busy = await ev('!!document.querySelector(\'button[aria-label="停止生成"]\')')
  const hasCard = await ev('document.body.innerText.indexOf("ALIGO / FX") >= 0')
  if (hasCard && !busy) break
}
await sleep(2000)
const r = await send('Page.captureScreenshot',{format:'png'})
writeFileSync('data/public-demo.png', Buffer.from(r.result.data,'base64'))
console.log('screenshot saved; FX card:', await ev('document.body.innerText.indexOf("ALIGO / FX") >= 0'))
ws.close(); edge.kill(); process.exit(0)