import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeReplyMarkdown } from '../src/utils/replyMarkdown.ts'

test('旧的功能介绍恢复为三个独立列表项，后面的示例不并入列表', () => {
  assert.equal(normalizeReplyMarkdown('我可以帮你做这些：\r\n· 查天气\r\n• 查政策\r\n· 规划行程\r\n直接说需求就行。'),
    '我可以帮你做这些：\n- 查天气\n- 查政策\n- 规划行程\n\n直接说需求就行。')
})

test('保持已排版回复、段落内间隔号和代码原样', () => {
  const source = '**开始**\n\n- 第一项\n- 第二项\n\n广州 · 上海\n\n~~~text\n· 不转换\n~~~\n\n    • 缩进代码'
  assert.equal(normalizeReplyMarkdown(source), source)
})
