// 截图采集：每个场景独立用户（干净侧栏）+ 自动重试 + 结构化判定
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE = 'http://127.0.0.1:3003'
const PORT = Number(process.env.CDP_PORT || 9361)
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const OUT = 'docs/screenshots'
const profile = mkdtempSync(join(tmpdir(), 'aligo-shots2-'))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
mkdirSync(OUT, { recursive: true })

const edge = spawn(EDGE, ['--headless=new','--disable-gpu','--hide-scrollbars','--force-device-scale-factor=1','--remote-debugging-port='+PORT,'--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','about:blank'], { stdio: 'ignore' })
async function findPage() {
  for (let i = 0; i < 50; i++) {
    try { const l = await (await fetch('http://127.0.0.1:'+PORT+'/json/list')).json(); const p = l.find(x => x.type === 'page'); if (p?.webSocketDebuggerUrl) return p.webSocketDebuggerUrl } catch {}
    await sleep(300)
  }
  throw new Error('CDP not ready')
}
const ws = new WebSocket(await findPage())
await new Promise(r => ws.addEventListener('open', r, { once: true }))
let id = 0; const pend = new Map()
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id) } })
const send = (m, p = {}) => { const i = ++id; return new Promise(r => { pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })) }) }
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true }); return r.result?.result?.value }
const shot = async (n) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(OUT, n + '.png'), Buffer.from(r.result.data, 'base64')); return n }

await send('Page.enable'); await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

async function fresh(user) {
  await send('Page.navigate', { url: BASE })
  await sleep(1200)
  await ev('try{localStorage.setItem("aligo_user_id",' + JSON.stringify(user) + ')}catch(e){}; true')
  await send('Page.navigate', { url: BASE })
  await sleep(3200)
  await ev("document.documentElement.classList.remove('dark'); true")
  await sleep(500)
}

async function ask(text, maxWait) {
  const typed = await ev('(function(){var ta=document.querySelector("textarea");if(!ta)return 0;var s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set;s.call(ta,' + JSON.stringify(text) + ');ta.dispatchEvent(new Event("input",{bubbles:true}));return 1})()')
  if (!typed) return false
  await sleep(450)
  let clicked = false
  for (let i = 0; i < 100; i++) {
    if (await ev('(function(){var b=[].slice.call(document.querySelectorAll("button")).filter(function(x){return x.getAttribute("aria-label")==="发送消息"&&!x.disabled})[0];if(b){b.click();return true}return false})()')) { clicked = true; break }
    await sleep(300)
  }
  if (!clicked) return false
  const deadline = Date.now() + (maxWait || 90000)
  let sawBusy = false
  while (Date.now() < deadline) {
    await sleep(1200)
    const busy = await ev('!!document.querySelector(\'button[aria-label="停止生成"]\')')
    if (busy) sawBusy = true
    else if (sawBusy) break
  }
  await sleep(2000)
  return true
}

// 完成判定：不能用「存在 paper-raised 容器」——处理中的进度卡也用同一个 class，
// 曾因此拍到一张 97s 仍显示「停止」的中间态。改为：无停止按钮 + 无错误 +
// 正文出现结果 eyebrow（ALIGO / XXX）且已无「处理中」字样。
const isErr = async () => await ev('!!document.querySelector("[role=alert]")')
const isDone = async () => await ev(`(function(){
  var t = document.body.innerText;
  if (document.querySelector('button[aria-label="停止生成"]')) return false;
  if (t.indexOf('ALIGO / 处理中') >= 0) return false;
  return /ALIGO \\/ (ITINERARY|RAIL|INFO|PREFERENCES|EXPENSE|FX|KNOWLEDGE)/.test(t);
})()`)

const SCENES = [
  { name: '02-itinerary', user: 'demo_itinerary', q: '明天北京到上海，3 天，预算 2000', tries: 3 },
  { name: '04-weather', user: 'demo_weather', q: '北京天气怎么样', tries: 2 },
  { name: '05-train', user: 'demo_train', q: '北京到上海的高铁票', tries: 2 },
  { name: '06-preference', user: 'demo_pref', q: '我喜欢住万豪，座位要靠窗，请记住', tries: 2 },
  { name: '07-expense', user: 'demo_expense', q: '记一笔打车费 50 元', tries: 2 },
  { name: '08-currency', user: 'demo_currency', q: '100 美元等于多少人民币', tries: 2 },
  { name: '09-rag', user: 'demo_rag', q: '出差住宿标准是多少', tries: 2 },
]

const results = []
for (const s of SCENES) {
  let ok = false
  for (let t = 1; t <= s.tries && !ok; t++) {
    await fresh(s.user + '_' + t)
    const sent = await ask(s.q, 95000)
    if (!sent) { console.log(s.name, 'attempt', t, '=> cannot send'); continue }
    const err = await isErr()
    const done = await isDone()
    if (!err && done) {
      const n = await shot(s.name)
      console.log(s.name, 'attempt', t, '=> OK', n)
      ok = true
    } else {
      console.log(s.name, 'attempt', t, '=> retry (err=' + err + ' done=' + done + ')')
    }
  }
  results.push({ name: s.name, ok })
}

// 首页空状态
await fresh('demo_home')
console.log('01-home =>', await shot('01-home'))

console.log('SUMMARY', JSON.stringify(results))
ws.close(); edge.kill(); process.exit(0)