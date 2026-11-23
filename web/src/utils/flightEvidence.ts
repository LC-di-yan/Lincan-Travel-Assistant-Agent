import { asRecord } from './resultData.ts'

export const evidenceText = (value: unknown) => typeof value === 'string' ? value.trim() : ''

export function publicLink(value: unknown) {
  try {
    const url = new URL(evidenceText(value))
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined
  } catch {
    return undefined
  }
}

export function evidenceSources(...groups: unknown[]) {
  const links = new Map<string, { title: string; url?: string }>()
  for (const group of groups) {
    if (!Array.isArray(group)) continue
    for (const value of group) {
      const row = asRecord(value)
      const url = publicLink(row.url)
      const title = evidenceText(row.title) || (url ? new URL(url).hostname : '')
      if (title && !links.has(url || title)) links.set(url || title, { title, url })
    }
  }
  return [...links.values()]
}

export function beijingQueryTime(value: unknown) {
  const raw = evidenceText(value)
  if (!/(?:Z|[+-]\d\d:\d\d)$/i.test(raw)) return ''
  const ms = Date.parse(raw)
  if (!Number.isFinite(ms)) return ''
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(ms)
  const part = (type: string) => parts.find(p => p.type === type)?.value
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`
}

export function activityTime(value: unknown) {
  const text = evidenceText(value)
  return /^(?:[-—–]+|待定|待确认|未知|未定|时间待定|时刻待定|未提供|待核验|n\/?a)?$/i.test(text) ? '' : text
}

export function seatStatus(value: unknown) {
  const text = typeof value === 'number' && Number.isInteger(value) && value >= 0 ? String(value) : evidenceText(value)
  if (text === '无' || text === '0') return { text: '无', known: true }
  if (!text || /^[-—–*]+$/.test(text) || ['未知', '未提供'].includes(text)) return { text: '未提供', known: false }
  return { text, known: true }
}

export function mapReference(value: unknown) {
  const raw = typeof value === 'number' && Number.isFinite(value) ? String(value) : evidenceText(value)
  if (!raw || /^(?:\[\s*\]|[-—–*]+|暂无|未知|未提供|null|n\/?a)$/i.test(raw)) return { kind: 'missing', raw: '' } as const
  const parts = raw.split(/[-–—~～到至]/).map(part => part.trim())
  if (parts.length <= 2 && parts.every(p => /^[¥￥]?\s*(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d{1,2})?\s*元?$/.test(p))) {
    const numbers = parts.map(part => part.replace(/[￥¥元,，\s]/g, ''))
    const amounts = numbers.map(Number)
    if (amounts.every(Number.isFinite) && amounts.every(n => n === 0)) return { kind: 'missing', raw: '' } as const
    if (amounts[0] > 0 && amounts.every(Number.isFinite) && (amounts.length === 1 || amounts[1] >= amounts[0])) {
      return { kind: 'reference', raw: `¥${numbers.join('–')}` } as const
    }
  }
  return { kind: 'unclear', raw } as const
}

export function amapMarker(value: unknown, name: string) {
  const coordinates = evidenceText(value)
  if (!/^-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?$/.test(coordinates)) return undefined
  const [lng, lat] = coordinates.split(',').map(Number)
  if (Math.abs(lng) > 180 || Math.abs(lat) > 90 || (lng === 0 && lat === 0)) return undefined
  return 'https://uri.amap.com/marker?' + new URLSearchParams({ position: `${lng},${lat}`, name }).toString()
}
