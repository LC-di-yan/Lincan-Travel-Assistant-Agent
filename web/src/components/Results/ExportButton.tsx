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
      lines.push('DTSTART:' + fmtDate(start))
      lines.push('DTEND:' + fmtDate(end))
      lines.push('SUMMARY:' + (act.activity || '行程'))
      if (act.description) lines.push('DESCRIPTION:' + act.description)
      lines.push('UID:' + crypto.randomUUID())
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
    lines.push('\n' + plan.day)
    for (const act of plan.activities || []) {
      const time = act.time ? '[' + act.time + '] ' : ''
      lines.push('  ' + time + (act.activity || ''))
      if (act.description) lines.push('    ' + act.description)
      if (act.transport) lines.push('    交通: ' + act.transport)
    }
    if (plan.meals?.lunch) lines.push('  午餐: ' + plan.meals.lunch)
    if (plan.meals?.dinner) lines.push('  晚餐: ' + plan.meals.dinner)
  }

  if (itinerary.notes?.length) {
    lines.push('\n注意事项:')
    itinerary.notes.forEach((n, i) => lines.push('  ' + (i + 1) + '. ' + n))
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

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function ExportButton({ itinerary }: { itinerary: Itinerary }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    const first = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')
    first?.focus()
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  const handleICS = () => {
    const ics = generateICS(itinerary)
    downloadFile(ics, (itinerary.title || '行程') + '.ics', 'text/calendar')
    setOpen(false)
  }

  const handleText = () => {
    const text = generateText(itinerary)
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
    setOpen(false)
  }

  const handlePrint = () => {
    const text = generateText(itinerary)
    const win = window.open('', '_blank')
    if (win) {
      win.document.write(
        '<pre style="font-family: ui-monospace, Consolas, monospace; white-space: pre-wrap; padding: 2rem; line-height: 1.7;">' +
        escapeHtml(text) +
        '</pre>',
      )
      win.document.close()
      win.print()
    }
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-8 items-center gap-1 rounded-[2px] border border-rule-strong px-2 text-[11px] font-medium text-ink-2 hover:bg-paper-sunken hover:text-ink"
      >
        <Download size={12} aria-hidden="true" /> 导出
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label="导出行程"
          className="absolute right-0 top-full z-50 mt-1 min-w-[150px] overflow-hidden rounded-[2px] border border-rule bg-paper-raised shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={handlePrint}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[12px] text-ink-2 hover:bg-paper-sunken hover:text-ink"
          >
            <FileText size={13} aria-hidden="true" /> 打印 / PDF
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={handleICS}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[12px] text-ink-2 hover:bg-paper-sunken hover:text-ink"
          >
            <Calendar size={13} aria-hidden="true" /> 日历 (.ics)
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={handleText}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[12px] text-ink-2 hover:bg-paper-sunken hover:text-ink"
          >
            {copied ? <Check size={13} className="text-ok" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
            {copied ? '已复制' : '复制文本'}
          </button>
        </div>
      )}
    </div>
  )
}
