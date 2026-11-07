// 前端视觉/行为验证：Edge + CDP（与项目 e2e 同机制，无需 Playwright）
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const BASE = 'http://127.0.0.1:3003'
const PORT = 9344
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const profile = mkdtempSync(join(tmpdir(), 'aligo-visual-'))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
mkdirSync('data/visual', { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + profile,
  '--no-first-run', '--no-default-browser-check',
  'about:blank',
], { stdio: 'ignore' })

async function findPage() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json()
      const p = list.find((x) => x.type === 'page')
      if (p?.webSocketDebuggerUrl) return p.webSocketDebuggerUrl
    } catch {}
    await sleep(300)
  }
  throw new Error('CDP not ready')
}

const wsUrl = await findPage()
const ws = new WebSocket(wsUrl)
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
let id = 0
const pending = new Map()
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
function send(method, params = {}) {
  const myId = ++id
  return new Promise((res) => { pending.set(myId, res); ws.send(JSON.stringify({ id: myId, method, params })) })
}
async function evaluate(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
  return r.result?.result?.value
}
async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync('data/visual/' + name + '.png', Buffer.from(r.result.data, 'base64'))
  return 'data/visual/' + name + '.png'
}

await send('Page.enable')
await send('Runtime.enable')

// 桌面浅色
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: BASE })
await sleep(3500)
// 应用默认跟随系统，可能是深色；先显式置浅色再截图
await evaluate(`document.documentElement.classList.remove('dark'); true`)
await sleep(500)
console.log('desktop-light:', await shot('desktop-light'))

// 检查触感反馈与主题 token 是否真的生效
const probe = await evaluate(`(() => {
  const btn = document.querySelector('button:not([data-press="off"])');
  const cs = btn ? getComputedStyle(btn) : null;
  const root = getComputedStyle(document.documentElement);
  return JSON.stringify({
    buttons: document.querySelectorAll('button').length,
    transitionProperty: cs ? cs.transitionProperty : null,
    transitionDuration: cs ? cs.transitionDuration : null,
    paper: root.getPropertyValue('--paper').trim(),
    accent: root.getPropertyValue('--accent').trim(),
    logRegion: !!document.querySelector('[role="log"][aria-live]'),
    emojiInDom: (document.body.innerText.match(/[\\u{1F300}-\\u{1FAFF}\\u{2600}-\\u{27BF}]/gu) || []).length
  });
})()`)
console.log('PROBE', probe)

// 深色
await evaluate(`document.documentElement.classList.add('dark')`)
await sleep(600)
console.log('desktop-dark:', await shot('desktop-dark'))

// 移动端（粗指针）
await evaluate(`document.documentElement.classList.remove('dark')`)
await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true })
await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })
await sleep(900)
console.log('mobile-light:', await shot('mobile-light'))
const touch = await evaluate(`(() => {
  const bs = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
  const small = bs.filter(b => b.getBoundingClientRect().height < 44 && !b.hasAttribute('data-press'));
  return JSON.stringify({ visibleButtons: bs.length, under44: small.length,
    samples: small.slice(0,5).map(b => (b.getAttribute('aria-label') || b.innerText.slice(0,12)) + '=' + Math.round(b.getBoundingClientRect().height)) });
})()`)
console.log('TOUCH', touch)

ws.close()
edge.kill()
process.exit(0)