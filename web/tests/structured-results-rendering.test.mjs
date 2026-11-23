import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

// 直接离线渲染真实卡片，以合成数据验证排版内容，不调用外部接口。
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
    if (url.startsWith(sourceRoot) && /\.tsx?$/.test(url)) return {
      format: 'module', shortCircuit: true,
      source: ts.transpileModule(readFileSync(fileURLToPath(url), 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2023 },
      }).outputText,
    }
    return nextLoad(url, context)
  },
})

const { InfoCard } = await import('../src/components/Results/InfoCard.tsx')
const { PreferenceCard } = await import('../src/components/Results/PreferenceCard.tsx')
const { PreferencePanelContent } = await import('../src/components/Sidebar/PreferencePanel.tsx')
const { PREFERENCE_ICONS } = await import('../src/components/Icons/categoryIcons.ts')
const render = (Component, data) => renderToStaticMarkup(createElement(Component, { data })).replace(/<!--[\s\S]*?-->/g, '')
const count = (html, value) => html.split(value).length - 1
const tomorrow = { start_date: '2026-11-19', end_date: '2026-11-19', label: '明天', include_current: false }
const day = { date: '明天 11/19 周四', date_iso: '2026-11-19', weather: '阴', night_weather: '小雨', temp_range: '-2~7°C' }
const weather = (results) => render(InfoCard, { query_type: '天气查询', results })

test('新版天气只展示结构化预报，建议、描述、缺数说明和交通各保留一次', () => {
  const travel = '白天建议备伞，注意路面安全。'
  const clothing = '建议穿厚外套；夜间加一件保暖内搭。'
  const note = '第三天暂无可靠预报，不使用其他日期替代。'
  const transport = '市内交通建议：乘地铁 2 号线；末班时间请核对运营公告。'
  const description = '注意带伞'
  const html = weather({
    presentation_version: 2, city: '北京', requested_range: tomorrow,
    current: { temp: '28', weather: '晴' },
    forecast: [{ ...day, description }],
    advice: [{ date_iso: day.date_iso, date: day.date, travel_tips: travel, clothing_advice: clothing }],
    weather_notes: [note], transport_advice: { summary: transport },
    summary: `北京天气【明天】\n📅所查日期预报\n${day.date}：白天阴，夜间小雨，气温 -2~7℃；${description}\n💡${day.date}出行提醒（基于预报）：${travel}\n👕${day.date}穿衣建议（基于预报）：${clothing}\n${note}\n\n${transport}`,
  })
  for (const value of [day.date, day.temp_range, travel, clothing, note, transport, description]) assert.equal(count(html, value), 1, value)
  assert.doesNotMatch(html, /所查日期预报|北京天气【明天】|当前实况|text-\[32px\]|>28<\/span>/)
  assert.match(html, /2026-11-19/)
})

test('新版今天实况与全天预报各一份，保留风湿度和真实观测时间', () => {
  const observedAt = '2026-11-18 10:30:00'
  const queriedAt = '2026-11-18 10:42:00'
  const clothing = '建议穿羽绒服或厚外套。'
  const html = weather({
    presentation_version: 2,
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-18', label: '今天', include_current: true },
    current: { temp: '-2.5', weather: '阴', wind: '北风 3级', humidity: 62, observed_at: observedAt, queried_at: queriedAt },
    forecast: [{ ...day, date: '今天 11/18 周三', date_iso: '2026-11-18', temp_range: '-4~7°C' }],
    advice: [{ date_iso: '2026-11-18', date: '今天', clothing_advice: clothing }],
    weather_notes: [],
    summary: `当前实况 -2.5℃，今日全天预报 -4~7℃。\n👕今日穿衣建议：${clothing}`,
  })
  assert.equal(count(html, '当前实况'), 1)
  assert.equal(count(html, '-2.5'), 1)
  assert.equal(count(html, '-4~7°C'), 1)
  assert.equal(count(html, clothing), 1)
  assert.match(html, /北风 3级 · 湿度 62%/)
  assert.equal(count(html, observedAt), 1)
  assert.doesNotMatch(html, /10:42:00/)
})

test('新版未提供观测时间时不把查询时间当作观测时间', () => {
  const html = weather({
    presentation_version: 2,
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-18', label: '今天', include_current: true },
    current: { temp: 7, weather: '阴', observed_at: '', queried_at: '2026-11-18 10:42:00' },
    forecast: [], advice: [], weather_notes: [], summary: '当前气温 7℃。',
  })
  assert.match(html, /当前实况/)
  assert.doesNotMatch(html, /观测时间|10:42:00/)
})

test('新版缺少有效结构时回退人话摘要，不因版本标记留下空卡', () => {
  const summary = '天气服务暂时不可用，未取得明天的可靠预报，请稍后重试。'
  const error = '天气请求超时'
  for (const fields of [
    {},
    { current: null, forecast: [], advice: [], weather_notes: [] },
    { current: { temp: '?' }, forecast: [null, {}, { date_iso: day.date_iso, date: day.date }], advice: [null, {}], weather_notes: [null, ''] },
  ]) {
    const html = weather({ presentation_version: 2, requested_range: tomorrow, summary, error, ...fields })
    assert.equal(count(html, summary), 1)
    assert.equal(count(html, error), 1)
    assert.doesNotMatch(html, /当前实况|text-\[32px\]/)
  }
})

test('新版仅有错误说明时保留完整说明，重复错误仍只展示一次', () => {
  const error = '当前天气来源不可用，请稍后重试。'
  const html = weather({ presentation_version: 2, requested_range: tomorrow, summary: error, error, weather_notes: [error] })
  assert.equal(count(html, error), 1)
  assert.match(html, /text-err/)
})

test('新版区间查询逐日排版，缺失日期、错误和交通信息不因去重而丢失', () => {
  const note = '11 月 20 日暂无可靠数据，不作推测。'
  const error = '部分时段预报不可用'
  const transport = '交通建议：避免露天候车，保留换乘余量。'
  const html = weather({
    presentation_version: 2,
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-20', label: '三日天气', include_current: true },
    current: { temp: '20', weather: '晴' },
    forecast: [{ ...day, date_iso: '2026-11-18', date: '今天 11/18 周三', temp_range: '1~9°C' }, day],
    advice: [{ date_iso: day.date_iso, date: day.date, travel_tips: '注意雨雪和道路结冰。' }],
    weather_notes: [note, error, note], error,
    transport_advice: { summary: transport },
    sources: [{ title: '合成天气来源', url: 'https://example.test/weather' }],
    summary: `${note}\n${error}\n${transport}`,
  })
  assert.match(html, /2026-11-18 至 2026-11-20/)
  assert.equal(count(html, '<time '), 2)
  for (const value of ['1~9°C', day.temp_range, note, error, transport, '注意雨雪和道路结冰。']) assert.equal(count(html, value), 1, value)
  assert.doesNotMatch(html, /当前实况|>20<\/span>/)
  assert.match(html, /href="https:\/\/example.test\/weather"/)
})

test('旧版天气仅移除匹配的预报片段，保留独有附加提醒、穿衣及交通', () => {
  const travel = '合理安排户外活动，夜间注意保暖。'
  const clothing = '建议穿长袖内搭和外套。'
  const note = '部分日期超出可用范围，其余日期暂无可靠预报。'
  const transport = '交通建议：优先乘坐地铁，末班车时间需另行核对。'
  const html = weather({
    city: '北京', requested_range: tomorrow, forecast: [day],
    transport_advice: { summary: transport },
    summary: `北京天气【明天】\n📅所查日期预报\n${day.date}：白天阴，夜间小雨，气温 -2~7℃；雨天请带伞套\n${note}\n💡${day.date}出行提醒（基于预报）：${travel}\n👕${day.date}穿衣建议（基于预报）：${clothing}\n\n${transport}`,
  })
  assert.equal(count(html, '-2~7'), 1)
  for (const value of ['雨天请带伞套', travel, clothing, note, transport]) assert.equal(count(html, value), 1, value)
  assert.doesNotMatch(html, /所查日期预报|北京天气【明天】/)
})

test('旧版自然语言摘要剔除重复气温后仍保留后面的独有建议', () => {
  const html = weather({ requested_range: tomorrow, forecast: [day], summary: '明天气温 -2~7°C，出门请备伞；路面湿滑，请预留时间。' })
  assert.equal(count(html, '-2~7°C'), 1)
  assert.equal(count(html, '出门请备伞；路面湿滑，请预留时间。'), 1)
})

test('旧版实况移除重复事实但不把旧摘要的查询时间当成观测时间', () => {
  const html = weather({
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-18', label: '今天', include_current: true },
    current: { temp: '-2.5', weather: '阴', wind: '北风 3级', humidity: '62' },
    forecast: [{ ...day, date: '今天 11/18 周三', date_iso: '2026-11-18' }],
    summary: '🌞当前实况（2026-11-18 10:42，北京时间）\n阴，气温 -2.5℃\n北风 3级，湿度 62%\n👕今日穿衣建议：外出请穿保暖外套。',
  })
  for (const value of ['当前实况', '-2.5', '北风 3级', '湿度 62%', '外出请穿保暖外套。']) assert.equal(count(html, value), 1, value)
  assert.match(html, /查询时间：2026-11-18 10:42，北京时间/)
  assert.doesNotMatch(html, /观测时间/)
})

test('实况日期与所查未来日期不一致时不展示当前气温', () => {
  const html = weather({
    presentation_version: 2, requested_range: { ...tomorrow, include_current: true },
    current: { date_iso: '2026-11-18', temp: '28', weather: '晴' },
    forecast: [day], advice: [], weather_notes: [], summary: '当前实况 28℃，明天预报 -2~7℃。',
  })
  assert.doesNotMatch(html, /当前实况|>28<\/span>/)
  assert.equal(count(html, day.temp_range), 1)
})

test('旧数据缺少实况日期时不凭include_current将未来查询误称当前实况', () => {
  const html = weather({
    requested_range: { ...tomorrow, include_current: true }, current: { temp: '28', weather: '晴' },
    forecast: [day], summary: '明天气温 -2~7°C，出行请备伞。',
  })
  assert.doesNotMatch(html, /当前实况|>28<\/span>/)
  assert.equal(count(html, day.temp_range), 1)
  assert.equal(count(html, '出行请备伞。'), 1)
})

test('旧版多日请求以紧凑实况保留独有温度风湿度，不放大或重复原始实况', () => {
  const html = weather({
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-20', label: '三日天气', include_current: true },
    current: { temp: '-2.5', weather: '阴', wind: '北风 3级', humidity: '62' },
    forecast: [day],
    summary: '🌞当前实况（2026-11-18 10:42，北京时间）\n阴，气温 -2.5℃\n北风 3级，湿度 62%\n明天气温 -2~7°C，出行请备伞。',
  })
  for (const value of ['本次实况', '-2.5°C', '北风 3级', '湿度 62%', day.temp_range, '查询时间：2026-11-18 10:42，北京时间', '出行请备伞。']) assert.equal(count(html, value), 1, value)
  assert.doesNotMatch(html, /当前实况|text-\[32px\]|观测时间/)
})

test('多日实况明确日期位于区间内部时保留，区间外或未来请求则不混入实况', () => {
  const requested = { start_date: '2026-11-17', end_date: '2026-11-19', label: '三日天气', include_current: true }
  const current = { date_iso: '2026-11-18', temp: '8.5', weather: '晴', observed_at: '2026-11-18 10:30:00' }
  const html = weather({ presentation_version: 2, requested_range: requested, current, forecast: [day], summary: '当前气温 8.5℃。' })
  assert.equal(count(html, '本次实况'), 1)
  assert.equal(count(html, '8.5°C'), 1)
  assert.equal(count(html, '观测时间：2026-11-18 10:30:00'), 1)
  assert.doesNotMatch(html, /text-\[32px\]/)
  for (const fields of [
    { requested_range: { ...requested, include_current: false }, current },
    { requested_range: requested, current: { ...current, date_iso: '2026-11-16' } },
  ]) {
    const futureHtml = weather({ presentation_version: 2, forecast: [day], summary: '明天气温 -2~7°C。', ...fields })
    assert.doesNotMatch(futureHtml, /本次实况|当前实况|8\.5°C|10:30:00/)
    assert.equal(count(futureHtml, day.temp_range), 1)
  }
})

test('旧版摘要没有可匹配结构时保持完整，交通对象独有内容也能展示', () => {
  const summary = '暂未取得所查日期可靠气温，无法判断衣物厚度，请临近出行时确认。'
  const transport = '市内交通建议：乘坐公交前核对临时绕行公告。'
  const html = weather({ requested_range: tomorrow, forecast: [], summary, transport_advice: { summary: transport } })
  assert.equal(count(html, summary), 1)
  assert.equal(count(html, transport), 1)
  assert.doesNotMatch(html, /当前实况/)
})

test('偏好类型展示中文标签，不泄露内部英文键且保留中文自定义类型', () => {
  const preferences = [
    ['transportation_preference', '地铁', '交通偏好'],
    ['meal_preference', '清淡', '餐食偏好'],
    ['budget_level', '经济', '预算等级'],
    ['food_preference', '江浙菜', '美食偏好'],
    ['hotel_brands', '汉庭', '酒店品牌'],
    ['seat_preference', '靠窗', '座位偏好'],
    ['custom_internal_key', '晨间出行', '其他偏好'],
    ['晨跑偏好', '公园', '晨跑偏好'],
  ]
  const html = render(PreferenceCard, { preferences: preferences.map(([type, value]) => ({ type, value })) })
  for (const [type, value, label] of preferences) {
    assert.match(html, new RegExp(label))
    assert.equal(count(html, value), 1)
    if (/^[a-z_]+$/.test(type)) assert.equal(count(html, type), 0, type)
  }
})

test('已保存偏好侧栏与结果卡片共用中文标签，新交通餐食预算字段归入对应分组', () => {
  const entries = [
    ['transportation_preference', '地铁优先', '交通偏好'],
    ['transport_preference', '公交优先', '交通偏好'],
    ['meal_preference', '清淡餐食', '餐食偏好'],
    ['food_preference', '江浙菜', '美食偏好'],
    ['dietary_preference', '少糖饮食', '饮食偏好'],
    ['budget_level', '经济实用', '预算等级'],
    ['hotel_brand', '汉庭酒店', '酒店品牌'],
    ['home', '杭州', '常住城市'],
    ['custom_internal_key', '晨间出行', '其他偏好'],
    ['custom_内部字段', '暂存选项', '其他偏好'],
    ['晨跑偏好', '河边公园', '晨跑偏好'],
  ]
  const card = render(PreferenceCard, { preferences: entries.map(([type, value]) => ({ type, value })) })
  const sidebar = renderToStaticMarkup(createElement(PreferencePanelContent, {
    preferences: Object.fromEntries(entries.map(([type, value]) => [type, value])), loading: false, onRefresh() {},
  }))
  for (const [type, value, label] of entries) {
    assert.ok(card.includes(`>${label}</div>`), `卡片标签：${label}`)
    assert.ok(sidebar.includes(`title="${label}"`), `侧栏标签：${label}`)
    assert.ok(sidebar.includes(`aria-label="${label}：${value}"`), `侧栏说明：${label}`)
    if (/[a-z_]/i.test(type)) {
      assert.equal(count(card, type), 0, type)
      assert.equal(count(sidebar, type), 0, type)
    }
  }
  const sections = sidebar.match(/<section\b[\s\S]*?<\/section>/g) || []
  const stay = sections.find((section) => section.includes('住宿出行')) || ''
  const life = sections.find((section) => section.includes('生活方式')) || ''
  const travel = sections.find((section) => section.includes('旅行偏好')) || ''
  assert.ok(stay.includes('title="交通偏好"'))
  assert.ok(stay.includes('title="酒店品牌"'))
  for (const label of ['餐食偏好', '美食偏好', '饮食偏好', '预算等级']) assert.ok(life.includes(`title="${label}"`), label)
  assert.ok(travel.includes('title="常住城市"'))
})

test('偏好类型别名使用一致图标，不回退为无关图钉', () => {
  for (const [alias, original] of [
    ['transportation_preference', 'transport'], ['transport_preference', 'transport'],
    ['meal_preference', 'food'], ['food_preference', 'food'], ['dietary_preference', 'dietary'],
    ['budget_level', 'budget'],
  ]) {
    assert.ok(PREFERENCE_ICONS[alias], alias)
    assert.equal(PREFERENCE_ICONS[alias], PREFERENCE_ICONS[original], alias)
  }
})
