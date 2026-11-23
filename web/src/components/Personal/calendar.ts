import type { PlanVersion } from '../../api/personal'

const clean = (value: string) => value.replace(/\\/g, '\\\\').replace(/\r?\n/g, '\\n').replace(/[;,]/g, '\\$&')
const stamp = (value: string) => new Date(value).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z')

function fold(line: string) {
  const chunks: string[] = []
  const encoder = new TextEncoder()
  let chunk = '', bytes = 0
  for (const point of line) {
    const next = encoder.encode(point).length
    if (bytes + next > 75) {
      chunks.push(chunk)
      chunk = ' '; bytes = 1
    }
    chunk += point
    bytes += next
  }
  chunks.push(chunk)
  return chunks.join('\r\n')
}

export function calendarText(plan: PlanVersion, now = new Date()) {
  const snap = plan.snapshot
  const selected = snap.options.find((option) => option.option_id === snap.selected_option_id)
  const events = [...(snap.schedule_items || []), ...(selected?.schedule_items || [])]
    .filter((event) => event.precision === 'exact' && event.start_at && event.end_at && event.event_id)
  if (!events.length) return null
  const rows = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Aligo//Personal itinerary//ZH', 'CALSCALE:GREGORIAN']
  for (const event of events) {
    rows.push('BEGIN:VEVENT', `UID:${event.event_id}@aligo.local`, `DTSTAMP:${stamp(now.toISOString())}`,
      `DTSTART:${stamp(event.start_at!)}`, `DTEND:${stamp(event.end_at!)}`, `SUMMARY:${clean(event.title)}`,
      `LOCATION:${clean(event.place || event.city || '')}`, 'END:VEVENT')
  }
  return rows.map(fold).concat('END:VCALENDAR', '').join('\r\n')
}

export function downloadCalendar(text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/calendar;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'aligo-calendar.ics'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
