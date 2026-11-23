import { useCallback, useEffect, useState } from 'react'

type Loader<T> = (signal: AbortSignal) => Promise<T>
type Loaded<T> = { loader: Loader<T>; token: number; data: T | null; error: string }

export function usePersonalResource<T>(loader: Loader<T>) {
  const [result, setResult] = useState<Loaded<T> | null>(null)
  const [token, setToken] = useState(0)
  const retry = useCallback(() => setToken((n) => n + 1), [])
  const current = result?.loader === loader && result.token === token ? result : null

  useEffect(() => {
    const controller = new AbortController()
    loader(controller.signal).then((value) => {
      if (!controller.signal.aborted) setResult({ loader, token, data: value, error: '' })
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setResult({
        loader, token, data: null, error: err instanceof Error ? err.message : '暂时无法读取资料。',
      })
    })
    return () => controller.abort()
  }, [loader, token])

  return { data: current?.data ?? null, error: current?.error ?? '', loading: !current, retry }
}
