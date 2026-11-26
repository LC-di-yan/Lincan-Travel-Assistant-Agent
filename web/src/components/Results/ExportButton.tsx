import { useState, useRef, useEffect } from 'react'
import { Download, FileText, Calendar, Copy, Check } from 'lucide-react'
import type { Itinerary } from '../../api/types'
import { generateICS } from '../../utils/calendar'
import { activityTime, evidenceSources } from '../../utils/flightEvidence'

function generateText(itinerary: Itinerary): string {
  const lines: string[] = []
  lines.push(itinerary.title || '行程')
  if (itinerary.duration) lines.push(itinerary.duration)
  if (itinerary.route) lines.push('路线示意: ' + itinerary.route)
  if (itinerary.estimated_budget) lines.push('预计预算: ' + itinerary.estimated_budget)
  lines.push(itinerary.price_notice || '票价、房价与可订状态未核验。')
  for (const source of evidenceSources(itinerary.sources)) lines.push('来源: ' + source.title + (source.url ? ' ' + source.url : ''))
  lines.push('─'.repeat(30))

  for (const plan of itinerary.daily_plans || []) {
    lines.push('\n' + [typeof plan.day === 'number' ? `第 ${plan.day} 天` : plan.day, plan.date, plan.city, plan.theme].filter(Boolean).join(' · '))
    for (const act of plan.activities || []) {
      const time = '[' + (activityTime(act.time) || '时刻待核验') + '] '
      lines.push('  ' + time + (act.activity || act.location || '未命名活动'))
      if (act.location && act.activity && act.location !== act.activity) lines.push('    地点: ' + act.location)
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
  const [exportError, setExportError] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
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
    const first = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')
    first?.focus()
  }, [open])

  const handleICS = () => {
    try {
      const ics = generateICS(itinerary)
      downloadFile(ics, (itinerary.title || '行程') + '.ics', 'text/calendar')
      setExportError('')
      setOpen(false)
      trigger.current?.focus()
    } catch (error) {
      setExportError(error instanceof Error ? error.message : '日历暂时无法导出')
    }
  }

  const handleText = async () => {
    try {
      await navigator.clipboard.writeText(generateText(itinerary))
      setCopied(true)
      setExportError('')
    } catch { setExportError('无法复制，请使用打印或手动复制。') }
    finally { setOpen(false); trigger.current?.focus() }
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
    trigger.current?.focus()
  }

  return (
    <div ref={ref} className="relative shrink-0"
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
      }}
      onKeyDown={event => {
        if (!open || event.key !== 'Escape') return
        event.preventDefault()
        setOpen(false)
        trigger.current?.focus()
      }}>
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-8 items-center gap-1 rounded-[2px] border border-rule-strong px-2 text-[11px] font-medium text-ink-2 hover:bg-paper-sunken hover:text-ink"
      >
        {copied ? <Check size={12} aria-hidden="true" /> : <Download size={12} aria-hidden="true" />} 导出
      </button>

      {copied && <p role="status" className="sr-only">行程文本已复制</p>}
      {exportError && <p role="alert" className="max-w-64 text-[11px] text-err">{exportError}</p>}
      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label="导出行程"
          onKeyDown={event => {
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
            const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
            const current = items.findIndex(item => item === document.activeElement)
            const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
              : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
            event.preventDefault()
            items[index]?.focus()
          }}
          className="absolute right-0 top-full z-50 mt-1 min-w-[150px] overflow-hidden rounded-input border border-rule border-t-2 border-t-route bg-paper-raised shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={handlePrint}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[12px] text-ink-2 hover:bg-paper-sunken hover:text-ink"
          >
            <FileText size={13} aria-hidden="true" /> 打印 / PDF
          </button>
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={handleICS}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[12px] text-ink-2 hover:bg-paper-sunken hover:text-ink"
          >
            <Calendar size={13} aria-hidden="true" /> 日历 (.ics)
          </button>
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
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
