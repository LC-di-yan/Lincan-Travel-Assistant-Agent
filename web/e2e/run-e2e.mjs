import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const BASE = (process.env.BASE_URL || 'http://127.0.0.1:3003').replace(/\/$/, '')
const MODE = process.env.MODE || 'heavy'
const PORT = Number(process.env.CDP_PORT || 9333)
const USER = process.env.USER_ID || 'e2e_auto_' + Date.now()
const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const PROFILE = mkdtempSync(join(tmpdir(), 'aligo-e2e-'))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

async function waitDebugger() {
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json()
      const page = list.find((x) => x.type === 'page')
      if (page?.webSocketDebuggerUrl) return page
    } catch {
      // wait
    }
    await sleep(300)
  }
  throw new Error('Edge debugger did not start on port ' + PORT)
}

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check',
  '--autoplay-policy=no-user-gesture-required',
  '--user-data-dir=' + join(PROFILE, 'profile'),
  '--window-size=1440,1000',
  '--remote-debugging-port=' + PORT,
  'about:blank',
], { stdio: 'ignore' })

let ws
let msgId = 0
const pending = new Map()
const api = []
const errors = []

try {
  const page = await waitDebugger()
  ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m)
      pending.delete(m.id)
      return
    }
    if (m.method === 'Network.responseReceived' && m.params.response.url.includes('/api/')) {
      api.push({ status: m.params.response.status, url: m.params.response.url.replace(BASE, '') })
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      errors.push(m.params.args.map((a) => a.value || a.description || '').join(' '))
    }
    if (m.method === 'Runtime.exceptionThrown') {
      errors.push('EX ' + (m.params.exceptionDetails?.exception?.description || ''))
    }
  }

  const send = (method, params = {}) => new Promise((res) => {
    const id = ++msgId
    pending.set(id, res)
    ws.send(JSON.stringify({ id, method, params }))
  })

  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'evaluate failed')
    return r.result?.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Network.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

  await send('Page.navigate', { url: BASE + '/' })
  await sleep(1500)
  await evaluate("localStorage.setItem('aligo_user_id','" + USER + "')")
  await evaluate("localStorage.removeItem('aligo_session_id')")
  await evaluate("localStorage.setItem('aligo-tts-prefs-v3', JSON.stringify({personaId:'loli_guide',autoPlay:" + (MODE === 'audio' ? 'true' : 'false') + "}))")
  await send('Page.reload')
  await sleep(2200)

  const state = () => evaluate("(() => ({ processing: !!document.querySelector('button[aria-label=\"停止生成\"]'), cards: [...document.querySelectorAll('[data-agent]')].map((c) => c.getAttribute('data-agent')), text: ([...document.querySelectorAll('[data-message-role=\"assistant\"]')].at(-1)?.innerText || '').slice(0, 1200), starts: window.__ttsStarts || 0 }))()")

  const waitUntil = async (expression, timeoutMs, label) => {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return
      await sleep(2500)
    }
    throw new Error('timeout: ' + label)
  }

  const sendMessage = async (text) => {
    const expr = "(() => { const ta=document.querySelector('textarea[aria-label=\"输入消息\"]'); if(!ta) return 'no textarea'; const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set; setter.call(ta," + JSON.stringify(text) + "); ta.dispatchEvent(new Event('input',{bubbles:true})); const btn=document.querySelector('button[aria-label=\"发送消息\"]'); if(!btn) return 'no send'; btn.click(); return 'sent'; })()"
    const r = await evaluate(expr)
    assert(r === 'sent', 'send failed: ' + r)
  }

  if (MODE === 'heavy') {
    await sendMessage('明天从北京去上海出差3天，预算2000，帮我排一份行程')
    await waitUntil("(() => !document.querySelector('button[aria-label=\"停止生成\"]') && !!document.querySelector('[data-agent=\"itinerary_planning\"]'))()", 130000, 'itinerary card')
    const itinerary = await evaluate("document.querySelector('[data-agent=\"itinerary_planning\"]')?.innerText || ''")
    assert(itinerary.includes('ALIGO / ITINERARY'), 'itinerary card missing header')
    assert(itinerary.includes('第 1 天'), 'numeric day not rendered')

    await sendMessage('上海静安寺附近有哪些酒店')
    await waitUntil("(() => !document.querySelector('button[aria-label=\"停止生成\"]') && !!document.querySelector('[data-agent=\"hotel_search\"]'))()", 100000, 'hotel card')
    const hotel = await evaluate("document.querySelector('[data-agent=\"hotel_search\"]')?.innerText || ''")
    assert(hotel.includes('酒店搜索'), 'hotel card missing title')
    assert(!hotel.includes('未找到相关结果'), 'hotel card is empty')
    console.log('PASS heavy: itinerary + hotel cards rendered')
  } else {
    await evaluate("window.__ttsStarts=0; const orig=AudioBufferSourceNode.prototype.start; AudioBufferSourceNode.prototype.start=function(...a){window.__ttsStarts++; return orig.apply(this,a)};")
    await evaluate("document.querySelector('button[aria-label=\"语音设置\"]')?.click()")
    await sleep(800)
    const rect = await evaluate("(() => { const b=document.querySelector('button[aria-label^=\"试听\"]'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()")
    assert(rect, 'TTS preview button not found')
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: rect.x, y: rect.y, button: 'left', clickCount: 1 })
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: rect.x, y: rect.y, button: 'left', clickCount: 1 })
    await waitUntil('window.__ttsStarts > 0', 20000, 'TTS audio buffer scheduling')
    assert(api.some((x) => x.url.startsWith('/api/tts') && x.status === 200), 'TTS HTTP 200 not observed')

    await evaluate("localStorage.setItem('aligo-tts-prefs-v3', JSON.stringify({personaId:'loli_guide',autoPlay:true}))")
    await send('Page.reload')
    await sleep(2200)
    await evaluate("window.__ttsStarts=0; const orig=AudioBufferSourceNode.prototype.start; AudioBufferSourceNode.prototype.start=function(...a){window.__ttsStarts++; return orig.apply(this,a)};")
    await sendMessage('我的偏好是什么')
    await waitUntil('window.__ttsStarts > 0', 70000, 'narrate -> TTS playback')
    assert(api.some((x) => x.url.startsWith('/api/narrate') && x.status === 200), 'narrate HTTP 200 not observed')
    console.log('PASS audio: TTS preview + narrate -> TTS playback')
  }

  assert(errors.length === 0, 'console errors: ' + errors.join(' | '))
  const bad = api.filter((x) => x.status >= 400)
  assert(bad.length === 0, 'API errors: ' + JSON.stringify(bad))
  console.log('PASS api calls:', api.length, 'errors: 0')
} catch (err) {
  console.error('FAIL', err.message)
  try {
    if (ws) {
      const shot = await new Promise((res) => {
        const id = ++msgId
        pending.set(id, res)
        ws.send(JSON.stringify({ id, method: 'Page.captureScreenshot', params: { format: 'png' } }))
      })
      if (shot?.result?.data) writeFileSync('e2e-failure.png', Buffer.from(shot.result.data, 'base64'))
    }
  } catch {
    // ignore
  }
  process.exitCode = 1
} finally {
  try { ws?.send(JSON.stringify({ id: ++msgId, method: 'Browser.close' })) } catch { /* ignore */ }
  try { ws?.close() } catch { /* ignore */ }
  await sleep(800)
  edge.kill('SIGKILL')
  await sleep(300)
  try { rmSync(PROFILE, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }) } catch { /* Edge may still hold the profile */ }
  if (process.env.KEEP_USER !== '1') {
    try { rmSync(resolve(import.meta.dirname, '../../data/memory/' + USER + '.json'), { force: true }) } catch { /* ignore */ }
  }
}
