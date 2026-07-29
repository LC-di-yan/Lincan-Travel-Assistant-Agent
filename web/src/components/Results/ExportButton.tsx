import { useState, useRef, useEffect } from 'react'
import { Download, FileText, Calendar, Copy, Check } from 'lucide-react'
import type { Itinerary } from '../../api/types'

function generateICS(itinerary: Itinerary): string {
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Aligo Travel//CN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
  ]

  const today = new Date()
  let dayOffset = 0

  for (const plan of itinerary.daily_plans || []) {
    const date = new Date(today)
    date.setDate(date.getDate() + dayOffset)

    for (const act of plan.activities || []) {
      const timeStr = act.time || '09:00'
      const [h, m] = timeStr.split(':').map(Number)
      const start = new Date(date)
      start.setHours(h, m, 0, 0)
      const end = new Date(start)
      end.setHours(h + 1, m, 0, 0)

      const fmtDate = (d: Date) => d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'

      lines.push('BEGIN:VEVENT')
      lines.push(`DTSTART:${fmtDate(start)}`)
      lines.push(`DTEND:${fmtDate(end)}`)
      lines.push(`SUMMARY:${act.activity || '行程'}`)
      if (act.description) lines.push(`DESCRIPTION:${act.description}`)
      lines.push(`UID:${crypto.randomUUID()}`)
      lines.push('END:VEVENT')
    }
    dayOffset++
  }

  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

function generateText(itinerary: Itinerary): string {
  const lines: string[] = []
  lines.push(itinerary.title || '行程')
  if (itinerary.duration) lines.push(itinerary.duration)
  lines.push('─'.repeat(30))

  for (const plan of itinerary.daily_plans || []) {
    lines.push(`\n${plan.day}`)
    for (const act of plan.activities || []) {
      const time = act.time ? `[${act.time}] ` : ''
      lines.push(`  ${time}${act.activity || ''}`)
      if (act.description) lines.push(`    ${act.description}`)
      if (act.transport) lines.push(`    🚗 ${act.transport}`)
    }
    if (plan.meals?.lunch) lines.push(`  🍽️ 午餐: ${plan.meals.lunch}`)
    if (plan.meals?.dinner) lines.push(`  🍽️ 晚餐: ${plan.meals.dinner}`)
  }

  if (itinerary.notes?.length) {
    lines.push('\n注意事项:')
    itinerary.notes.forEach((n, i) => lines.push(`  ${i + 1}. ${n}`))
  }

  return lines.join('\n')
}

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function ExportButton({ itinerary }: { itinerary: Itinerary }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleICS = () => {
    const ics = generateICS(itinerary)
    downloadFile(ics, `${itinerary.title || '行程'}.ics`, 'text/calendar')
    setOpen(false)
  }

  const handleText = () => {
    const text = generateText(itinerary)
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
    setOpen(false)
  }

  const handlePrint = () => {
    const text = generateText(itinerary)
    const win = window.open('', '_blank')
    if (win) {
      win.document.write(`<pre style="font-family: inherit; white-space: pre-wrap; padding: 2rem;">${text}</pre>`)
      win.document.close()
      win.print()
    }
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-all hover:bg-white/20"
        style={{ color: 'rgba(255,255,255,0.85)' }}
      >
        <Download size={14} /> 导出
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 rounded-xl overflow-hidden z-50 min-w-[140px]"
          style={{
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          <button onClick={handlePrint} className="flex items-center gap-2 w-full px-3 py-2.5 text-xs hover:bg-[var(--bg-secondary)] transition-colors">
            <FileText size={13} /> 打印 / PDF
          </button>
          <button onClick={handleICS} className="flex items-center gap-2 w-full px-3 py-2.5 text-xs hover:bg-[var(--bg-secondary)] transition-colors">
            <Calendar size={13} /> 日历 (.ics)
          </button>
          <button onClick={handleText} className="flex items-center gap-2 w-full px-3 py-2.5 text-xs hover:bg-[var(--bg-secondary)] transition-colors">
            {copied ? <Check size={13} className="text-green-500" /> : <Copy size={13} />}
            {copied ? '已复制' : '复制文本'}
          </button>
        </div>
      )}
    </div>
  )
}
