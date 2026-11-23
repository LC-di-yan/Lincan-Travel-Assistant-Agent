import type { Itinerary } from '../api/types'

export function generateICS(itinerary: Itinerary): string {
  const escape = (value: string) => value.replace(/\\/g, '\\\\').replace(/\r?\n|\r/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;')
  const format = (value: Date) => value.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Aligo Travel//CN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
  const stamp = format(new Date())
  for (const plan of itinerary.daily_plans || []) {
    const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(plan.date || '')
    if (!parts) throw new Error('行程缺少具体日期，请先补全日期后再导出日历')
    const [, year, month, day] = parts.map(Number)
    const base = new Date(year, month - 1, day)
    if (base.getFullYear() !== year || base.getMonth() !== month - 1 || base.getDate() !== day) throw new Error('行程日期无效，请检查后再导出')
    for (const activity of plan.activities || []) {
      const time = (activity.time || '09:00').replace(/：/g, ':').replace(/[—–~～至]/g, '-').trim()
      const match = /^(\d{1,2}):(\d{2})(?:\s*-\s*(\d{1,2}):(\d{2}))?$/.exec(time)
      if (!match) throw new Error(`无法识别活动时间“${activity.time}”，请使用 09:00-12:00 格式`)
      const startHour = Number(match[1]), startMinute = Number(match[2])
      const endHour = match[3] === undefined ? startHour + 1 : Number(match[3])
      const endMinute = match[4] === undefined ? startMinute : Number(match[4])
      if (startHour > 23 || startMinute > 59 || endHour > 24 || endMinute > 59 || (match[3] !== undefined && endHour === 24 && endMinute !== 0)) throw new Error('活动时间超出有效范围')
      const start = new Date(year, month - 1, day, startHour, startMinute)
      const end = new Date(year, month - 1, day, endHour, endMinute)
      if (end < start) end.setDate(end.getDate() + 1)
      if (end.getTime() === start.getTime()) throw new Error('活动结束时间不能与开始时间相同')
      lines.push('BEGIN:VEVENT', 'DTSTAMP:' + stamp, 'DTSTART:' + format(start), 'DTEND:' + format(end), 'SUMMARY:' + escape(activity.activity || '行程'))
      if (activity.description) lines.push('DESCRIPTION:' + escape(activity.description))
      const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}@aligo`
      lines.push('UID:' + id, 'END:VEVENT')
    }
  }
  lines.push('END:VCALENDAR')
  // 日历规定每行最多 75 个字节，中文不能按字符串长度截断。
  return lines.map((line) => {
    const encoder = new TextEncoder()
    const result: string[] = []
    let current = '', size = 0
    for (const character of line) {
      const length = encoder.encode(character).length
      if (size + length > 75) { result.push(current); current = ' '; size = 1 }
      current += character
      size += length
    }
    result.push(current)
    return result.join('\r\n')
  }).join('\r\n') + '\r\n'
}
