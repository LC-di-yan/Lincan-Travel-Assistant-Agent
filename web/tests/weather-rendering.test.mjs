import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

// 用真实结果卡片执行离线渲染，不请求天气接口或浏览器。
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

const { InfoCard } = await import('../src/components/Results/InfoCard.tsx')
const render = (data) => renderToStaticMarkup(createElement(InfoCard, { data })).replace(/<!--[\s\S]*?-->/g, '')
const tomorrow = {
  start_date: '2026-11-19', end_date: '2026-11-19', label: '明天', include_current: false,
}
const day = (date = '2026-11-19', range = '-2~7°C', label = '明天 11/19 周四') => ({
  date: label, date_iso: date, weather: '阴', night_weather: '小雨', temp_range: range,
})
const weather = (results, extra = {}) => ({ query_type: '天气查询', query_success: true, results, ...extra })
const noCurrentHero = (html) => {
  assert.doesNotMatch(html, /text-\[32px\]/)
  assert.doesNotMatch(html, /当前实况/)
}

test('未来预报保留完整负温区间，不把区间上限显示成当前温度', () => {
  const html = render(weather({
    city: '北京', requested_range: tomorrow, forecast: [day()], summary: '明天气温 -2~7°C，出门请备伞。',
  }))
  noCurrentHero(html)
  assert.match(html, /天气预报/)
  assert.match(html, /北京 · 天气简报/)
  assert.match(html, /明天 · 2026-11-19/)
  assert.match(html, /<time[^>]+2026-11-19/)
  assert.match(html, /-2~7°C/)
  assert.doesNotMatch(html, />7<\/span>/)
})

test('未来查询忽略附带的今日实况，只渲染所查日期的预报', () => {
  const html = render(weather({
    requested_range: tomorrow, current: { temp: '28', weather: '晴' },
    forecast: [day('2026-11-18', '19~28°C', '不在查询范围的今天'), day()],
    summary: '所查日期有雨，请注意保暖。',
  }))
  noCurrentHero(html)
  assert.doesNotMatch(html, /不在查询范围的今天|19~28°C|>28<\/span>/)
  assert.match(html, /明天 11\/19 周四/)
})

test('多日查询逐日展示日期及区间，不突出今天的实况温度', () => {
  const html = render(weather({
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-20', label: '三日天气', include_current: true },
    current: { temp: '30', weather: '晴' },
    forecast: [day('2026-11-18', '18~30°C', '今天 11/18 周三'), day(), day('2026-11-20', '-3~5°C', '后天 11/20 周五')],
  }))
  noCurrentHero(html)
  assert.match(html, /天气预报/)
  assert.match(html, /2026-11-18 至 2026-11-20/)
  assert.equal((html.match(/<time /g) || []).length, 3)
  for (const range of ['18~30°C', '-2~7°C', '-3~5°C']) assert.ok(html.includes(range))
})

test('仅查询今天时，实况温度只取结构化 current 字段并保留负号小数', () => {
  const html = render(weather({
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-18', label: '今天', include_current: true },
    current: { temp: '-2.5', weather: '阴' },
    forecast: [day('2026-11-18', '-4~7°C', '今天 11/18 周三')],
    summary: '今日全天预报 -4~7°C。',
  }))
  assert.match(html, /当前实况/)
  assert.match(html, /text-\[32px\][^>]*>-2\.5<\/span>/)
  assert.match(html, /-4~7°C/)
  assert.doesNotMatch(html, /text-\[32px\][^>]*>7<\/span>/)
})

test('无有效预报时保留缺数说明，不用摘要中的数字生成天气实况', () => {
  const html = render(weather({
    requested_range: tomorrow, forecast: [],
    summary: '暂未取得所查日期的可靠天气数据，不能使用其他日期的 20°C 替代。',
  }, { query_success: false }))
  noCurrentHero(html)
  assert.doesNotMatch(html, /<img/)
  assert.match(html, /暂未取得所查日期的可靠天气数据/)
  assert.match(html, /2026-11-19/)
})

test('只有天气摘要或无效 current 温度时不猜测实况', () => {
  for (const results of [
    { summary: '明天天气 -2~7°C。' },
    { requested_range: { ...tomorrow, include_current: true }, current: { temp: '?' }, summary: '天气预报 -2~7°C。' },
    { requested_range: { ...tomorrow, include_current: true }, current: { temp: '7°C' }, summary: '天气预报 -2~7°C。' },
  ]) noCurrentHero(render(weather(results)))
})

test('交通建议和提到天气的普通搜索不误判为天气卡片', () => {
  for (const query_type of ['交通建议', '网络搜索']) {
    const html = render({ query_type, results: { summary: '天气可能降到 -2~7°C，建议乘坐地铁。' } })
    noCurrentHero(html)
    assert.match(html, /搜索结果/)
    assert.doesNotMatch(html, /天气信息|天气预报|<img/)
    assert.match(html, /建议乘坐地铁/)
  }
})

test('部分日期缺数时按请求跨度识别多日，不放大仅有的今天实况', () => {
  const html = render(weather({
    requested_range: { start_date: '2026-11-18', end_date: '2026-11-21', label: '四日天气', include_current: true },
    current: { temp: 7, weather: '晴' }, forecast: [day('2026-11-18', '-2~7°C', '今天')],
    partial: true, summary: '其余日期暂无可靠预报，不作推测。',
  }))
  noCurrentHero(html)
  assert.match(html, /天气预报/)
  assert.match(html, /其余日期暂无可靠预报/)
})

test('保留复合交通建议、来源和嵌套错误信息', () => {
  const html = render(weather({
    requested_range: tomorrow, forecast: [day()],
    summary: '明天有雨。\n\n市内交通建议：优先乘坐地铁。',
    transport_advice: { summary: '市内交通建议：优先乘坐地铁。' },
    sources: [{ title: '高德天气', url: 'https://www.amap.com' }, { title: '交通来源', url: 'https://example.test/transport' }],
    error: '部分时段信息暂不可用',
  }))
  assert.match(html, /市内交通建议：优先乘坐地铁。/)
  assert.match(html, /href="https:\/\/www\.amap\.com\/"/)
  assert.match(html, /href="https:\/\/example.test\/transport"/)
  assert.match(html, /部分时段信息暂不可用/)
})

test('明确日期范围不采用无日期、畸形日期或区间外的预报行', () => {
  const html = render(weather({
    requested_range: tomorrow,
    forecast: [null, {}, day('2026-1-2', '1~2°C', '畸形日期'), day('2026-11-20', '3~4°C', '区间外日期'), day()],
  }))
  assert.equal((html.match(/<time /g) || []).length, 1)
  assert.doesNotMatch(html, /畸形日期|区间外日期/)
  assert.match(html, /-2~7°C/)
})
