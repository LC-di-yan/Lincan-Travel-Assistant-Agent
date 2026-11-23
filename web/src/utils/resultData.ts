export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

/** Preserve envelope metadata while accepting current and historical nested results. */
export function unwrapResultData(value: unknown): Record<string, unknown> {
  let data = asRecord(value)
  for (let depth = 0; depth < 10; depth++) {
    const inner = asRecord(data.data)
    if (Object.keys(inner).length === 0) break
    const { data: envelope, ...outer } = data
    void envelope
    data = { ...outer, ...inner }
  }
  return data
}
