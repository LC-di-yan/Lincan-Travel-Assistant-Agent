import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createElement } from 'react'
import { renderToReadableStream } from 'react-dom/server'

// Render the real message, dashboard and result components without a browser or API.
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
    if (url.startsWith(sourceRoot) && url.endsWith('.css')) {
      return { format: 'module', shortCircuit: true, source: '' }
    }
    if (url.startsWith(sourceRoot) && /\.tsx?$/.test(url)) {
      return {
        format: 'module', shortCircuit: true,
        source: ts.transpileModule(readFileSync(fileURLToPath(url), 'utf8'), {
          compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2023 },
        }).outputText,
      }
    }
    return nextLoad(url, context)
  },
})

const { MessageBubble } = await import('../src/components/Chat/MessageBubble.tsx')
const { extractTTSTexts } = await import('../src/utils/ttsText.ts')
const result = (agent_name, data, status = 'success') => ({ agent_name, data, status, priority: 1 })
const message = (agentResults, content = extractTTSTexts(agentResults)) => ({
  id: 'presentation-test', role: 'assistant', timestamp: 1, content, agentResults,
})
async function render(msg, props = {}) {
  const stream = await renderToReadableStream(createElement(MessageBubble, { msg, ...props }))
  await stream.allReady
  return (await new Response(stream).text()).replace(/<!--[\s\S]*?-->/g, '')
}
const count = (html, value) => html.split(value).length - 1
const noRawBody = (html) => assert.doesNotMatch(html, /class="markdown max-w-\[680px\]"/)

test('助手的路线反问只作提示，不是可以代发的用户消息', async () => {
  const question = '你的具体起点和终点是哪里，更在意省钱还是少换乘？'
  const value = result('information_query', { results: { summary: '这是北京交通建议。' }, proactive_question: question })
  const html = await render(message([value]), { isLatest: true, onSend() { assert.fail('不应发送助手提问') } })
  const notice = html.match(/<aside aria-label="助手的后续提问"[^>]*>[\s\S]*?<\/aside>/)?.[0]
  assert.ok(notice)
  assert.ok(notice.includes(question))
  assert.doesNotMatch(notice, /<button|帮我问/)
  assert.equal(count(html, question), 1)
})

test('铁路失败只显示一次中文原因，不显示内部技能名或其他车次建议', async () => {
  const error = '暂未获取中转换乘方案，请前往12306查询。'
  const value = result('train_ticket', {
    availability_status: 'unavailable', query_success: false, error,
    results: { from: '上海', to: '北京', date: '2026-11-21', message: error },
  }, 'error')
  for (const msg of [message([value]), message([value], `train_ticket 执行失败：${error}`)]) {
    const html = await render(msg, { isLatest: true, onSend() {} })
    assert.equal(count(html, error), 1)
    assert.match(html, /上海 → 北京/)
    assert.doesNotMatch(html, /train_ticket 执行失败|其他车次|座位类型价格/)
    noRawBody(html)
  }
})

test('差旅方案区分已核验和候选，未知费用不按零展示且不可选择', async () => {
  const option = {
    id: 'verified', status: 'validated', budget_status: 'within', known_subtotals: { CNY: '2000' },
    outbound: { train_no: 'G100', from_station: '广州站', to_station: '上海站', departs: '2026-11-23T09:00:00+08:00' },
    hotel: { name: '合成住宿' }, commute: { duration_min: 11 },
    cost_items: [{ kind: 'other', amount: '200', currency: 'CNY', quality: 'user_budget' }],
  }
  const pending = { id: 'pending', status: 'provisional', budget_status: 'unverified', cost_items: [{ kind: 'inbound', amount: null }] }
  const data = {
    answer: '已验证的推荐方案与备选',
    trip_plan: {
      request: { origin: '广州', destination: '上海', depart_date: '2026-11-23', resolved_return_date: '2026-11-25', hotel_nights: 2 },
      recommended: option, alternatives: [option, pending], issues: [{ message: '返程票价待核验' }],
      validation: { note: '未执行预订。' },
    },
  }
  const msg = { ...message([result('itinerary_planning', data)], data.answer), orchestrationResult: { trip_plan: data.trip_plan } }
  const html = await render(msg, { isLatest: true, canSelectProposal: true, onSend() {} })
  assert.equal(count(html, data.answer), 1)
  assert.match(html, /预览方案 A/)
  assert.match(html, /预览方案 B/)
  assert.match(html, /2026-11-23 至 2026-11-25/)
  assert.match(html, /步行约 11 分钟/)
  assert.match(html, /返程票价待核验/)
  assert.match(html, /仅已知费用小计/)
  assert.match(html, /预览不等于确认/)
  assert.match(html, /选择方案 1/)
  assert.doesNotMatch(html, /选择方案 2/)
  assert.doesNotMatch(await render(msg, { isRunning: true, isLatest: true, canSelectProposal: true, onSend() {} }), /选择方案 1/)
  assert.doesNotMatch(await render({ ...msg, orchestrationResult: undefined }, { isLatest: true, canSelectProposal: true, onSend() {} }), /选择方案 1/)
})

test('费用预览不冒充写入，只有当前结果可确认', async () => {
  const code = '确认费用 ' + 'ab'.repeat(12)
  const value = result('expense_tracking', { action: 'preview', answer: '待新增打车费，尚未写入。', confirmation_command: code })
  const latest = await render(message([value]), { isLatest: true, onSend() {} })
  assert.match(latest, /待确认 · 账本未修改/)
  assert.match(latest, /确认这项费用操作/)
  assert.doesNotMatch(latest, /已记录|abababab/)
  assert.doesNotMatch(await render(message([value]), { onSend() {} }), /确认这项费用操作/)
  const history = await render({ ...message([value]), historical: true }, { isLatest: true, onSend() {} })
  assert.match(history, /预览快照 · 当时未写入/)
  assert.doesNotMatch(history, /确认这项费用操作|data-fresh/)
  const userHtml = await render({ role: 'user', id: 'confirm', content: code, timestamp: 1 })
  assert.match(userHtml, /确认费用操作/)
  assert.doesNotMatch(userHtml, /abababab/)
})

test('混币费用按来源分列，分类和退款保留原币；错误不冒充成功回执', async () => {
  const value = result('expense_tracking', { action: 'query', summary: {
    count: 2, total: null, currency: null, totals_by_currency: { CNY: 58, USD: -18.5 },
    by_category_by_currency: { CNY: { 交通: 58 }, USD: { 退款: -18.5 } },
  } })
  const html = await render(message([value]))
  assert.match(html, /CNY 58\.00/)
  assert.match(html, /USD -18\.50/)
  assert.match(html, /USD · 按类别/)
  assert.doesNotMatch(html, /39\.50|已确认|data-fresh/)
  const failure = await render(message([result('expense_tracker', { action: 'error', answer: '该确认已过期，未修改账本。' })]))
  assert.match(failure, /未收到成功回执/)
  assert.match(failure, /该确认已过期，未修改账本/)
  assert.doesNotMatch(failure, /账本已更新|data-fresh/)
})

test('铁路数据不可用时不展示实时余票、空车次或虚假票价', async () => {
  const value = result('train_ticket', { query_success: false, availability_status: 'unavailable',
    price_status: 'unavailable', results: { message: '暂未获取官方票价' } }, 'error')
  const html = await render(message([value]))
  assert.match(html, /数据暂不可用/)
  assert.match(html, /暂未获取官方票价/)
  assert.match(html, /https:\/\/www\.12306\.cn/)
  assert.doesNotMatch(html, /实时余票|0 趟|暂无余票/)
})

test('酒店地图价格标为参考，不能当作可订报价', async () => {
  const hotel = { id: 'audit', name: '合成酒店', cost: '300', address: '测试地址' }
  const html = await render(message([result('hotel_search', { results: { hotels: [hotel], count: 1 } })]))
  assert.match(html, /地图价格仅供参考/)
  assert.match(html, /参考 <span[^>]*>¥300<\/span>/)
})
const info = () => result('information_query', {
  query_type: '天气查询', results: {
    city: '北京', summary: '合成天气摘要：次日有小雨，建议携带雨具。',
    requested_range: { label: '明天', start_date: '2026-11-19', end_date: '2026-11-19', include_current: false },
    forecast: [{ date: '明天', date_iso: '2026-11-19', weather: '小雨', temp_range: '-2~7°C' }],
  },
})

test('天气卡片接管完整摘要，不再显示一份未排版正文', async () => {
  const value = info()
  const html = await render(message([value]))
  noRawBody(html)
  assert.equal(count(html, value.data.results.summary), 1)
  assert.match(html, /data-agent="information_query"/)
  assert.match(html, /-2~7°C/)
  assert.match(html, /朗读这条回复/)
})

test('偏好卡片接管确认文案，完整值保留在结构化卡片', async () => {
  const value = result('preference', {
    answer: '已记住您喜欢合成酒店和靠窗座位。',
    preferences: { preferences: [{ type: 'hotel_brand', value: ['合成酒店'] }, { type: 'seat_preference', value: '靠窗座位' }] },
  })
  const html = await render(message([value]))
  noRawBody(html)
  assert.match(html, /data-agent="preference"/)
  assert.equal(count(html, '合成酒店'), 1)
  assert.equal(count(html, '靠窗座位'), 1)
})

test('偏好确认后独有的机场打车附注保留一次，不因它同时是朗读文案而消失', async () => {
  const value = result('preference', {
    preferences: [{ type: 'seat_preference', value: '靠窗' }],
    answer: '偏好已更新。机场打车建议提前预约。', message: '合成提醒：周五路况较忙。',
  })
  const html = await render(message([value]))
  noRawBody(html)
  assert.match(html, /data-agent="preference"/)
  assert.equal(count(html, '机场打车建议提前预约。'), 1)
  assert.equal(count(html, '合成提醒：周五路况较忙。'), 1)
  assert.doesNotMatch(html, /偏好已更新。机场打车/)
})

test('费用记录与汇总都只在对应结果卡片内展示一次答案', async () => {
  for (const agent of ['expense_tracker', 'expense_tracking']) {
    for (const data of [
      { action: 'record', expense: { category: '交通', amount: 50, currency: 'USD' }, answer: '合成费用已记录，记得保留发票。' },
      { action: 'query', summary: { count: 2, total: 90, currency: 'USD' }, answer: '合成汇总包含两笔支出。' },
      { action: 'delete', answer: '合成费用已成功删除。' },
    ]) {
      const html = await render(message([result(agent, data)]))
      noRawBody(html)
      assert.equal(count(html, data.answer), 1)
      assert.match(html, /ALIGO \/ 费用回执/)
    }
  }
})

test('汇率别名共用卡片，数字换算和答案附加说明均不丢失', async () => {
  for (const agent of ['currency_converter', 'currency_conversion']) {
    const value = result(agent, { from: 'USD', to: 'CNY', amount: 100, result: 712.35, rate: 7.1235, answer: '合成换算完成；实际成交价以银行为准。' })
    const html = await render(message([value]))
    noRawBody(html)
    assert.match(html, /712\.35 CNY/)
    assert.equal(count(html, value.data.answer), 1)
  }
})

test('没有冗余答案字段的汇率结果仍有朗读入口且不会对数字调用 trim', async () => {
  const value = result('currency_converter', { from: 'USD', to: 'CNY', amount: 10, result: 72, rate: 7.2 })
  const html = await render(message([value], ''))
  assert.match(html, /72\.00 CNY/)
  assert.match(html, /朗读这条回复/)
  assert.equal(typeof extractTTSTexts([value]), 'string')
})

test('收据卡片不重新塞回重复的原始换算和记账句子，独有附注仍保留', async () => {
  for (const answer of [
    '100 美元 = 712.35 人民币 (参考汇率: 1 USD = 7.1235 CNY；汇率日期 2026-11-18)',
    '美元兑人民币参考汇率: 1 USD = 7.1235 CNY；汇率日期 2026-11-18',
  ]) {
    const value = result('currency_converter', { from: 'USD', to: 'CNY', amount: 100, result: 712.35, rate: 7.1235, rate_date: '2026-11-18', answer: answer + '；合成提醒：成交价以银行为准。' })
    const html = await render(message([value]))
    noRawBody(html)
    assert.doesNotMatch(html, /100 美元 =|美元兑人民币参考汇率/)
    assert.equal(count(html, '1 USD = 7.1235 CNY'), 1)
    assert.equal(count(html, '汇率日期 2026-11-18'), 1)
    assert.equal(count(html, '合成提醒：成交价以银行为准。'), 1)
  }
  const record = result('expense_tracking', {
    action: 'record', expense: { category: '交通', description: '合成打车', amount: 50, currency: 'CNY' },
    answer: '已记录：交通 - 合成打车 ¥50.00；合成提醒：请保留发票。',
  })
  const html = await render(message([record]))
  noRawBody(html)
  assert.doesNotMatch(html, /已记录：交通 -/)
  assert.equal(count(html, '合成打车'), 1)
  assert.equal(count(html, '合成提醒：请保留发票。'), 1)
})

test('知识、签证和未知文本技能均由可读卡片接管摘要或 JSON 答案', async () => {
  for (const agent of ['rag_knowledge', 'memory_query', 'visa_info', 'future_skill']) {
    for (const data of [{ summary: '合成政策回答，需要核对具体日期。' }, { answer: JSON.stringify({ answer: '合成嵌套答案。' }) }]) {
      const html = await render(message([result(agent, data)]))
      noRawBody(html)
      assert.match(html, new RegExp(`data-agent="${agent}"`))
      assert.equal(count(html, data.summary || '合成嵌套答案。'), 1)
      assert.doesNotMatch(html, /&quot;answer&quot;/)
    }
  }
})

test('翻译及历史字段别名只保留排版后的译文，缺失原文不误报翻译失败', async () => {
  for (const field of ['translated_text', 'translation', 'result', 'answer']) {
    const value = result('translation', { source_text: '合成原文', source_lang: 'zh', target_lang: 'en', [field]: 'Synthetic translation.' })
    const html = await render(message([value]))
    noRawBody(html)
    assert.equal(count(html, 'Synthetic translation.'), 1)
    assert.match(html, /复制译文/)
  }
  const html = await render(message([result('translation', { translated_text: 'Translation without source.' })]))
  assert.equal(count(html, 'Translation without source.'), 1)
  assert.doesNotMatch(html, /翻译失败/)
})

test('行程使用结构化标题和活动，未完成结果保留错误原因而非空白', async () => {
  const value = result('itinerary_planning', { itinerary: {
    title: '合成上海行程', duration: '1天', daily_plans: [{ day: 1, date: '2026-11-19', activities: [{ time: '09:00', activity: '合成客户会议', description: '准备演示资料' }] }],
  } })
  const html = await render(message([value]))
  noRawBody(html)
  assert.equal(count(html, '合成上海行程'), 1)
  assert.equal(count(html, '合成客户会议'), 1)
  assert.doesNotMatch(html, /已为您规划好/)
  const failed = result('itinerary_planning', { planning_complete: false, error: '合成规划缺少出发日期。' })
  const failedHtml = await render(message([failed]))
  assert.equal(count(failedHtml, '合成规划缺少出发日期。'), 1)
})

test('事项、展开列车和地点卡片保留所有已接管的摘要', async () => {
  const values = [
    result('event_collection', { origin: '北京', destination: '上海', message: '合成事项说明，需在周五抵达。' }),
    result('train_ticket', { expanded: true, summary: '合成列车提示，部分车次暂无余票。', results: { trains: [{ train_no: 'G123', second_class: '有', from_station: '北京南', to_station: '上海虹桥' }] } }),
    ...[['hotel_search', 'hotels'], ['restaurant_search', 'restaurants'], ['scenic_search', 'attractions']].map(([agent, key]) => result(agent, {
      summary: `合成${agent}摘要，营业安排以现场为准。`, results: { city: '上海', count: 1, [key]: [{ id: agent, name: `合成${agent}地点`, address: '合成路1号' }] },
    })),
  ]
  const html = await render(message(values))
  noRawBody(html)
  for (const value of values) assert.equal(count(html, value.data.summary || value.data.message), 1)
  assert.match(html, /G123/)
  for (const agent of ['hotel_search', 'restaurant_search', 'scenic_search']) assert.match(html, new RegExp(`data-agent="${agent}"`))
})

test('多层结果封装不吞掉外围摘要和错误元数据', async () => {
  const value = result('information_query', { error: '合成部分来源暂不可用', data: { data: info().data } })
  const html = await render(message([value]))
  noRawBody(html)
  assert.equal(count(html, info().data.results.summary), 1)
  assert.match(html, /合成部分来源暂不可用/)
  assert.match(html, /-2~7°C/)
})

test('混合技能逐段去重，同时保留独立正文、未知结果和嵌套执行错误', async () => {
  const values = [info(), result('memory_query', { answer: '合成差旅记忆。' }), result('future_skill', { text: '合成新技能结果。' }), result('train_ticket', { data: { error: '合成列车接口超时。' } }, 'error')]
  const html = await render(message(values, '独立建议：请先确认客户地址。\n\n' + extractTTSTexts(values) + '\n\n独立提醒：请携带身份证。'))
  for (const value of ['独立建议：请先确认客户地址。', '独立提醒：请携带身份证。', '合成差旅记忆。', '合成新技能结果。', '合成列车接口超时。']) assert.equal(count(html, value), 1)
  assert.match(html, /火车票 执行失败/)
  assert.equal(count(html, info().data.results.summary), 1)
})

test('只移除完整结果段落，不模糊删除包含相同短语的独立正文', async () => {
  const value = result('memory_query', { answer: '合成记忆。' })
  const independent = '我会结合“合成记忆。”继续核对，以下是独立建议。'
  const html = await render(message([value], independent))
  assert.match(html, /以下是独立建议/)
  assert.equal(count(html, '合成记忆。'), 2)
})

test('未知结构、空结果和不完整专用结果都不会生成空白或伪造零值', async () => {
  for (const value of [
    result('future_skill', { payload: { code: 42, note: '合成结构结果' } }),
    result('future_skill', {}),
    result('currency_converter', { answer: '合成汇率服务暂不可用。' }),
    result('itinerary_planning', { answer: '合成行程需要补充日期。' }),
  ]) {
    const html = await render(message([value]))
    assert.match(html, /ALIGO \/ KNOWLEDGE/)
    assert.doesNotMatch(html, /0\.00|暂无费用记录|翻译失败/)
    assert.match(html, /合成|暂时没有可展示的详细内容/)
  }
})

test('未知结果只显示人话说明或安全占位，不把内部对象和 JSON 答案原样倒给用户', async () => {
  for (const data of [
    { internal_payload: { debug_code: 42, opaque_internal: 'synthetic_internal_value' } },
    { answer: JSON.stringify({ internal_payload: { debug_code: 42 } }) },
    { payload: { note: '合成可读说明：结果尚待补充。', debug_code: 42 } },
  ]) {
    const html = await render(message([result('future_skill', data)]))
    assert.match(html, /合成可读说明|暂时没有可展示的详细内容/)
    assert.doesNotMatch(html, /<pre|<code|debug_code|internal_payload|opaque_internal|synthetic_internal_value|&quot;/)
  }
  const html = await render(message([result('future_skill', { answer: JSON.stringify({ answer: '第一条可读说明。', response: '第二条可读说明。' }) })]))
  assert.equal(count(html, '第一条可读说明。'), 1)
  assert.equal(count(html, '第二条可读说明。'), 1)
})

test('各类卡片未展示的独立 answer 或 message 不被误判为已接管正文', async () => {
  const note = '合成独立附注：机场接送需要提前预约。'
  const values = [
    result('information_query', { summary: '合成搜索摘要。', answer: note }),
    result('translation', { source_text: '合成原文', translated_text: 'Synthetic translation.', answer: note }),
    result('itinerary_planning', { itinerary: { title: '合成行程', daily_plans: [] }, answer: note }),
    result('event_collection', { summary: '合成事项摘要。', answer: note }),
    result('train_ticket', { results: { summary: '合成列车摘要。', trains: [] }, answer: note }),
    result('hotel_search', { results: { summary: '合成酒店摘要。', hotels: [] }, answer: note }),
    result('restaurant_search', { results: { summary: '合成餐厅摘要。', restaurants: [] }, answer: note }),
    result('scenic_search', { results: { summary: '合成景点摘要。', attractions: [] }, answer: note }),
    result('memory_query', { answer: '合成记忆答案。', message: note }),
    result('future_skill', { answer: '合成新技能答案。', message: note }),
  ]
  for (const value of values) {
    const html = await render(message([value], note))
    assert.equal(count(html, note), 1, value.agent_name)
    assert.match(html, /class="markdown max-w-\[680px\]"/, value.agent_name)
  }
})

test('仅有 answer 的执行错误也展示详情，嵌套旧消息无需改存储即可去重', async () => {
  for (const data of [{ answer: '合成失败详情：服务暂不可用。' }, { data: { answer: '合成失败详情：服务暂不可用。' } }]) {
    const value = result('train_ticket', data, 'error')
    const msg = Object.freeze(message([value]))
    const html = await render(msg)
    noRawBody(html)
    assert.match(html, /火车票 执行失败/)
    assert.equal(count(html, '合成失败详情：服务暂不可用。'), 1)
    assert.equal(msg.content, extractTTSTexts([value]))
  }
})

test('旧的无卡片消息和显式错误始终保留原文，用户消息不参与去重', async () => {
  const text = '合成旧消息内容。'
  const legacy = await render(message([], text))
  assert.equal(count(legacy, text), 1)
  const value = result('memory_query', { answer: text })
  const error = await render({ ...message([value], '合成网络断开，请重试。'), isError: true }, { onSend() {}, userMessage: '合成问题' })
  assert.match(error, /role="alert"/)
  assert.match(error, /合成网络断开，请重试。/)
  assert.match(error, /重试上一条消息/)
  const user = await render({ ...message([value]), role: 'user' })
  assert.equal(count(user, text), 1)
  assert.doesNotMatch(user, /ALIGO \/ KNOWLEDGE/)
})

test('流式结果到达后直接展示卡片，完成阶段不发生原始正文到卡片的闪变', async () => {
  const value = info()
  assert.equal(await render(message([], ''), { isRunning: true }), '')
  for (const content of ['', extractTTSTexts([value])]) {
    const running = await render(message([value], content), { isRunning: true })
    const completed = await render(message([value], content))
    noRawBody(running)
    noRawBody(completed)
    for (const html of [running, completed]) {
      assert.match(html, /data-agent="information_query"/)
      assert.equal(count(html, value.data.results.summary), 1)
    }
    assert.doesNotMatch(running, /朗读这条回复/)
    assert.match(completed, /朗读这条回复/)
  }
  const clarification = await render(message([], '合成澄清：请问哪一天出发？'), { isRunning: true })
  assert.match(clarification, /请问哪一天出发/)
})
