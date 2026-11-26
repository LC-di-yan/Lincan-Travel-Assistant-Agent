import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createElement } from 'react'
import { renderToReadableStream } from 'react-dom/server'

// 在现有 Node 测试中直接渲染真实组件，无需浏览器或额外测试依赖。
const sourceRoot = new URL('../src/', import.meta.url).href
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && context.parentURL?.startsWith(sourceRoot)) {
      const url = new URL(specifier, context.parentURL)
      for (const suffix of ['.ts', '.tsx', '/index.ts', '/index.tsx']) {
        const candidate = new URL(url.href + suffix)
        if (existsSync(candidate)) return { url: candidate.href, shortCircuit: true }
      }
    }
    return nextResolve(specifier, context)
  },
  load(url, context, nextLoad) {
    if (url.startsWith(sourceRoot) && url.endsWith('.css')) return { format: 'module', shortCircuit: true, source: '' }
    if (url.startsWith(sourceRoot) && /\.tsx?$/.test(url)) {
      const source = ts.transpileModule(readFileSync(fileURLToPath(url), 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2023 },
      }).outputText
      return { format: 'module', source, shortCircuit: true }
    }
    return nextLoad(url, context)
  },
})

const { MessageBubble } = await import('../src/components/Chat/MessageBubble.tsx')
const { extractTTSTexts } = await import('../src/utils/ttsText.ts')
const { sendChatMessage } = await import('../src/api/client.ts')

const memory = (data = { answer: '您在六月到杭州出差。' }) => ({
  agent_name: 'memory_query', priority: 1, status: 'success', data,
})
const message = (results, content = extractTTSTexts(results)) => ({
  id: 'memory-render-test', role: 'assistant', timestamp: 1, content, agentResults: results,
})
async function render(msg, props = {}) {
  const stream = await renderToReadableStream(createElement(MessageBubble, { msg, ...props }))
  await stream.allReady
  return (await new Response(stream).text()).replace(/<!--[\s\S]*?-->/g, '')
}
const count = (html, text) => html.split(text).length - 1

test('记忆查询完整答案只显示在结果卡片一次，朗读入口仍保留', async () => {
  const result = memory()
  const html = await render(message([result]))
  assert.equal(count(html, result.data.answer), 1)
  assert.match(html, /data-agent="memory_query"/)
  assert.match(html, /朗读这条回复/)
})

test('嵌套结果和 JSON 答案不造成正文与记忆卡片重复', async () => {
  const answer = '您在七月前往苏州出差。'
  const result = memory({ data: { answer: JSON.stringify({ answer }) } })
  const html = await render(message([result]))
  assert.equal(count(html, answer), 1)
  assert.doesNotMatch(html, /&quot;answer&quot;/)
})

test('记忆卡片保留多段答案和来源文档入口', async () => {
  const result = memory({ answer: '第一段差旅记录。\n\n第二段差旅记录。', sources: [{ document: '合成测试记录' }] })
  const html = await render(message([result]))
  assert.equal(count(html, '第一段差旅记录。'), 1)
  assert.equal(count(html, '第二段差旅记录。'), 1)
  assert.match(html, /来源文档（1）/)
})

test('混合技能分别由卡片接管副本，其他技能信息和执行错误仍存在', async () => {
  const result = memory()
  const info = { agent_name: 'information_query', priority: 2, status: 'success', data: { summary: '查询得到一条路线建议。' } }
  const error = { agent_name: 'train_ticket', priority: 3, status: 'error', data: { error: '合成测试错误' } }
  const html = await render(message([result, info, error]))
  assert.equal(count(html, result.data.answer), 1)
  assert.match(html, /data-agent="information_query"/)
  assert.equal(count(html, info.data.summary), 1)
  assert.match(html, /火车票 执行失败/)
  assert.match(html, /合成测试错误/)
})

test('没有可显示答案的记忆结果不吞掉正文', async () => {
  const result = memory({ summary: '暂无可展示的差旅记录。' })
  const html = await render(message([result]))
  assert.equal(count(html, result.data.summary), 1)
})

test('独立助手正文和错误消息不因存在记忆结果而被隐藏', async () => {
  const result = memory()
  const html = await render(message([result], '另外还需补充出差日期。'))
  assert.match(html, /另外还需补充出差日期。/)
  assert.equal(count(html, result.data.answer), 1)
  const errorHtml = await render({ ...message([result], '连接中断，请重试。'), isError: true }, {
    onSend() {}, userMessage: '查询我的差旅记录',
  })
  assert.match(errorHtml, /role="alert"/)
  assert.match(errorHtml, /连接中断，请重试。/)
  assert.match(errorHtml, /重试上一条消息/)
})

test('进行中已有结果即展示卡片而非先展示原始副本，用户消息保持原样', async () => {
  const result = memory()
  const msg = message([result])
  const runningHtml = await render(msg, { isRunning: true })
  assert.equal(count(runningHtml, result.data.answer), 1)
  assert.match(runningHtml, /data-agent="memory_query"/)
  assert.doesNotMatch(runningHtml, /class="markdown assistant-prose\b/)
  const userHtml = await render({ ...msg, role: 'user' })
  assert.equal(count(userHtml, result.data.answer), 1)
  assert.match(userHtml, /data-message-role="user"/)
})

test('SSE 分别交付一次子结果和最终快照，不额外重放子结果', async (t) => {
  const result = memory()
  const encoder = new TextEncoder()
  t.mock.method(globalThis, 'fetch', async (url) => {
    if (url === '/api/identity') return Response.json({ user_id: 'memory_test_user' })
    assert.equal(url, '/api/chat')
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode(`event: agent_result\ndata: ${JSON.stringify(result)}\n\n`))
      controller.enqueue(encoder.encode(`event: complete\ndata: ${JSON.stringify({ results: [result] })}\n\n`))
      controller.close()
    } }))
  })
  const received = [], complete = []
  await sendChatMessage('memory_test_user', '合成差旅查询', null, {
    onAgentResult: (value) => received.push(value),
    onComplete: (value) => complete.push(value),
  })
  assert.deepEqual(received, [result])
  assert.equal(complete.length, 1)
  assert.deepEqual(complete[0].results, [result])
})
