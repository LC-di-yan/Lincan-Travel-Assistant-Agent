import { asRecord } from './resultData.ts'

export function isExpenseConfirmation(value: unknown): value is string {
  return typeof value === 'string' && /^确认费用\s+[a-f0-9]{24}$/.test(value)
}

export function currencyCode(value: unknown) {
  return typeof value === 'string' && /^[A-Z]{3}$/i.test(value.trim()) ? value.trim().toUpperCase() : ''
}

function amountText(value: unknown) {
  const raw = typeof value === 'number' && Number.isFinite(value) ? String(value) : typeof value === 'string' ? value.trim() : ''
  const parsed = /^(-?\d{1,16})(?:\.(\d+))?$/.exec(raw)
  return parsed ? `${parsed[1]}.${(parsed[2] ?? '').padEnd(2, '0')}` : ''
}

export function originalAmount(value: unknown, currency: unknown) {
  const exact = amountText(value)
  if (!exact) return '金额未提供'
  const code = currencyCode(currency)
  return code ? `${code} ${exact}` : `${exact} · 币种未提供`
}

export function expenseTotals(raw: unknown, legacy?: { amount: unknown; currency: unknown }) {
  const provided = asRecord(raw)
  const hasBreakdown = Object.keys(provided).length > 0
  return hasBreakdown
    ? Object.entries(provided).flatMap(([currency, amount]) => {
      const code = currencyCode(currency)
      return code && amountText(amount) ? [{ currency: code, display: originalAmount(amount, code) }] : []
    })
    : legacy && amountText(legacy.amount)
      ? [{ currency: currencyCode(legacy.currency), display: originalAmount(legacy.amount, legacy.currency) }]
      : []
}
