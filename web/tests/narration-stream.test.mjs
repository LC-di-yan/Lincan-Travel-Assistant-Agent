import test from 'node:test'
import assert from 'node:assert/strict'
import { readNarration } from '../src/utils/narrationStream.ts'

const delta = 'event: delta\r\ndata: {"text":"完整文案"}\r\n\r\n'
const done = 'event: done\r\ndata: {}\r\n\r\n'

test('播报只采用正常结束的完整文案，兼容中文跨网络分片', async () => {
  const bytes = new TextEncoder().encode(delta + done)
  const stream = new ReadableStream({ start(c) {
    for (const byte of bytes) c.enqueue(Uint8Array.of(byte))
    c.close()
  } })
  assert.equal(await readNarration(new Response(stream)), '完整文案')
})

test('播报连接提前结束、错误或无内容时回退', async () => {
  for (const text of [delta, done, delta + 'event: error\ndata: {}\n\n' + done,
    delta + 'event: delta\ndata: invalid\n\n' + done]) {
    assert.equal(await readNarration(new Response(text)), null)
  }
  const broken = new ReadableStream({ pull(c) { c.error(new Error('断线')) } })
  assert.equal(await readNarration(new Response(broken)), null)
})
