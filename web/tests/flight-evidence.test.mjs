import test from 'node:test'
import assert from 'node:assert/strict'
import { activityTime, amapMarker, amapPhoto, beijingQueryTime, evidenceSources, mapReference, seatStatus } from '../src/utils/flightEvidence.ts'

test('高德照片限来源域名并升级到 HTTPS，不接受空图或无关地址', () => {
  assert.equal(amapPhoto('http://store.is.autonavi.com/a.jpg?size=2'), 'https://store.is.autonavi.com/a.jpg?size=2')
  assert.equal(amapPhoto('https://aos-comment.amap.com/b.jpg'), 'https://aos-comment.amap.com/b.jpg')
  for (const url of [undefined, [], 'blob:picture', 'https://amap.com.example.org/p.jpg', 'https://amap.com:444/a.jpg', 'https://account@amap.com/a.jpg']) {
    assert.equal(amapPhoto(url), undefined)
  }
})

test('缺时刻不生成时间，已有时段和跨天标记原样保留', () => {
  for (const time of ['', '—', '时间待定', null, '待核验']) assert.equal(activityTime(time), '')
  for (const time of ['上午', '09:35–11:00', '次日 06:05']) assert.equal(activityTime(time), time)
})

test('铁路明确无票、未提供席别和候补分别呈现，查询时间换算到北京', () => {
  assert.deepEqual(seatStatus('无'), { text: '无', known: true })
  assert.deepEqual(seatStatus(0), { text: '无', known: true })
  assert.deepEqual(seatStatus('--'), { text: '未提供', known: false })
  assert.deepEqual(seatStatus('候补'), { text: '候补', known: true })
  assert.equal(beijingQueryTime('2026-11-21T17:05:00Z'), '2026-11-22 01:05')
  assert.equal(beijingQueryTime('2026-11-21 17:05'), '')
})

test('地图参考价不虚构币种、房态或零元；无法解释的价格保留原文', () => {
  assert.deepEqual(mapReference('￥1,260.50 至 1,480 元'), { kind: 'reference', raw: '¥1260.50–1480' })
  assert.deepEqual(mapReference('USD 78/晚'), { kind: 'unclear', raw: 'USD 78/晚' })
  assert.deepEqual(mapReference('3,00'), { kind: 'unclear', raw: '3,00' })
  for (const price of [0, '', '[]', '--']) assert.equal(mapReference(price).kind, 'missing')
})

test('来源去重并保留名称；仅可用坐标才有高德定位入口', () => {
  const sources = evidenceSources([{ title: '来源甲', url: 'https://www.amap.com' }],
    [{ title: '重复来源', url: 'https://www.amap.com/' }, { title: '来源乙', url: 'javascript:void(0)' }])
  assert.deepEqual(sources, [{ title: '来源甲', url: 'https://www.amap.com/' }, { title: '来源乙', url: undefined }])
  for (const value of ['', '0,0', '181,0', '121.5,92', 'broken']) assert.equal(amapMarker(value, '住宿'), undefined)
  const url = new URL(amapMarker('121.5,31.2', '住宿 & 会场'))
  assert.equal(url.hostname, 'uri.amap.com')
  assert.equal(url.searchParams.get('name'), '住宿 & 会场')
  assert.equal(url.searchParams.get('position'), '121.5,31.2')
})
