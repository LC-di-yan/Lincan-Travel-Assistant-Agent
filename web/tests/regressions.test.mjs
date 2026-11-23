/** 直接测试独立核心模块；音频和请求均为模拟，不访问外部服务。 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { generateICS } from '../src/utils/calendar.ts'
import { TTSPlayer } from '../src/utils/ttsPlayer.ts'
import { formatMoney } from '../src/utils/money.ts'
import { generateSuggestions } from '../src/api/suggestionEngine.ts'
import { ensureIdentity, createSession } from '../src/api/client.ts'

process.env.TZ = 'Asia/Shanghai'
const itinerary = (time = '09:00-12:00', date = '2026-12-01') => ({
  daily_plans: [{ date, activities: [{ time, activity: '测试,活动;名称', description: '第一行\n第二行' }] }],
})

test('日历正确保留行程日期与时间段', () => {
  const result = generateICS(itinerary())
  assert.match(result, /DTSTART:20261201T010000Z/)
  assert.match(result, /DTEND:20261201T040000Z/)
})

test('单点时间提供一小时默认时长并支持跨午夜', () => {
  const result = generateICS(itinerary('23:30'))
  assert.match(result, /DTSTART:20261201T153000Z/)
  assert.match(result, /DTEND:20261201T163000Z/)
  const range = generateICS(itinerary('23:30-00:30'))
  assert.match(range, /DTEND:20261201T163000Z/)
})

test('日历拒绝缺失或无效的日期及时间而非生成错误事件', () => {
  for (const date of ['', '2026-02-30']) assert.throws(() => generateICS(itinerary('09:00', date)), /日期/)
  for (const time of ['25:00', '09:75', '09:00-24:30', '上午九点']) assert.throws(() => generateICS(itinerary(time)), /时间/)
})

test('日历字段正确转义且中文折行不超过字节限制', () => {
  const data = itinerary()
  data.daily_plans[0].activities[0].description += '中文'.repeat(80)
  const result = generateICS(data)
  assert.match(result, /SUMMARY:测试\\,活动\\;名称/)
  assert.match(result, /第一行\\n第二行/)
  for (const line of result.split('\r\n')) assert.ok(Buffer.byteLength(line) <= 75)
})

function setupAudio(t, fetchImpl) {
  const sources = [], samples = []
  class FakeAudioContext {
    state = 'running'
    currentTime = 0
    destination = {}
    createBuffer(channels, length, rate) { return { duration: length / rate, copyToChannel(value) { samples.push(Array.from(value)) } } }
    createBufferSource() {
      const source = { connect() {}, start() { source.started = true }, stop() { source.stopped = true }, onended: null }
      sources.push(source)
      return source
    }
  }
  const previous = globalThis.window
  globalThis.window = { AudioContext: FakeAudioContext }
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous })
  t.mock.method(globalThis, 'fetch', fetchImpl)
  return { player: new TTSPlayer(), sources, samples }
}

function audioResponse(chunks) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(encoder.encode(`event: audio\ndata: ${JSON.stringify({ chunk })}\n\n`))
    controller.enqueue(encoder.encode('event: done\ndata: {}\n\n'))
    controller.close()
  } }))
}

test('单个音频块在流结束时也能播放且结束事件清理状态', async (t) => {
  const { player, sources } = setupAudio(t, async () => audioResponse(['AAAAAA==']))
  const statuses = []
  await player.play('测试', { onStatus: (status) => statuses.push(status) })
  assert.equal(sources.length, 1)
  assert.ok(sources[0].started)
  assert.equal(statuses.at(-1), 'playing')
  sources[0].onended()
  assert.equal(statuses.at(-1), 'idle')
})

test('音频请求建立前停止不会访问已清空的控制器', async (t) => {
  let started
  const ready = new Promise((resolve) => { started = resolve })
  const { player } = setupAudio(t, (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('测试取消', 'AbortError')))
    started()
  }))
  const playing = player.play('测试')
  await ready
  player.stop()
  await assert.doesNotReject(playing)
})

test('PCM 奇数字节边界跨块拼接且不丢弃末尾音频', async (t) => {
  const { player, sources, samples } = setupAudio(t, async () => audioResponse(['AQAC', 'AA==']))
  await player.play('测试')
  assert.equal(sources.length, 2)
  assert.deepEqual(samples.flat(), [1 / 32768, 2 / 32768])
  player.stop()
})

test('切换播放后旧请求的取消不会停止新请求', async (t) => {
  let started
  const ready = new Promise((resolve) => { started = resolve })
  let count = 0
  const { player, sources } = setupAudio(t, (url, options) => {
    if (++count > 1) return Promise.resolve(audioResponse(['AAAAAA==']))
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('测试取消', 'AbortError')))
      started()
    })
  })
  const old = player.play('旧请求')
  await ready
  const statuses = []
  await player.play('新请求', { onStatus: (status) => statuses.push(status) })
  await old
  assert.equal(statuses.at(-1), 'playing')
  assert.ok(sources[0].started)
  assert.ok(!sources[0].stopped)
  player.stop()
})

test('金额显示保留原始币种', () => {
  assert.match(formatMoney(50, 'USD'), /US\$|USD/)
  assert.notEqual(formatMoney(50, 'USD'), formatMoney(50, 'CNY'))
})

test('费用金额不得作为城市拼进追问建议', () => {
  const suggestions = generateSuggestions({
    userMessage: '昨天花了50美元', persona: {},
    intention: { key_entities: { other: '交通 50元' }, intents: [{ type: 'expense_tracking' }] },
    agentResults: [{ agent_name: 'expense_tracking', data: { expense: { amount: 50, currency: 'USD' } } }],
  })
  assert.ok(suggestions.length > 0)
  assert.ok(suggestions.every((item) => !/50.*(?:住宿|餐补)/.test(item.query)))
})

test('并发初始化身份和会话只发送一份请求', async (t) => {
  let identities = 0, sessions = 0
  t.mock.method(globalThis, 'fetch', async (url) => {
    if (url === '/api/identity') { identities++; return Response.json({ user_id: 'user_test' }) }
    assert.equal(url, '/api/session/new')
    sessions++
    return Response.json({ user_id: 'user_test', session_id: 'session_test' })
  })
  const [first, second] = await Promise.all([ensureIdentity(), ensureIdentity()])
  assert.equal(first.user_id, second.user_id)
  await Promise.all([createSession(), createSession()])
  assert.equal(identities, 1)
  assert.equal(sessions, 1)
})
