export function proposalLetter(index: number) {
  return index >= 0 && index <= 25 ? String.fromCharCode(65 + index) : String(index + 1)
}

// The service sends decimal strings. Compare exact minor units and never infer a
// total from a subset of items, or a conversion between currencies.
function minorUnits(amount: unknown) {
  if (typeof amount !== 'string' && typeof amount !== 'number') return null
  const match = /^(\d{1,12})(?:\.(\d{1,2})0*)?$/.exec(String(amount))
  return match ? BigInt(match[1]) * 100n + BigInt((match[2] ?? '').padEnd(2, '0')) : null
}

export function verifiedCost(option: Record<string, unknown>) {
  if (!Array.isArray(option.cost_items) || !option.cost_items.length ||
      !option.known_subtotals || typeof option.known_subtotals !== 'object') return null
  const totals = Object.entries(option.known_subtotals)
  if (totals.length !== 1) return null
  const [currency, value] = totals[0]
  if (!/^[A-Z]{3}$/.test(currency)) return null
  const amount = minorUnits(value)
  if (amount === null) return null
  let sum = 0n
  const scope = new Set<string>()
  for (const item of option.cost_items) {
    if (!item || typeof item.kind !== 'string' || item.currency !== currency ||
        !['verified_quote', 'user_budget'].includes(item.quality) || scope.has(item.kind)) return null
    const part = minorUnits(item.amount)
    if (part === null) return null
    scope.add(item.kind)
    sum += part
  }
  return sum === amount ? { currency, amount, scope: [...scope].sort().join(',') } : null
}

export function compareProposalCosts(left: Record<string, unknown>, right: Record<string, unknown>) {
  const a = verifiedCost(left)
  const b = verifiedCost(right)
  if (!a || !b || a.currency !== b.currency || a.scope !== b.scope) return null
  return { currency: a.currency, delta: Number(b.amount - a.amount) / 100 }
}

export function comparisonPair(length: number, active: number) {
  if (length < 2) return null
  return [0, active > 1 && active < length ? active : 1] as const
}
