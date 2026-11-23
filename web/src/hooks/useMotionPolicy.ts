import { useEffect, useState } from 'react'

export type MotionChoice = 'system' | 'reduced' | 'static'
const key = 'aligo-motion'
function saved(): MotionChoice {
  try {
    const value = localStorage.getItem(key)
    if (value === 'static' || value === 'reduced') return value
  } catch { /* Storage is optional. */ }
  return 'system'
}

export function useMotionPolicy() {
  const [choice, setChoice] = useState<MotionChoice>(saved)
  const [systemReduce, setSystemReduce] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setSystemReduce(media.matches)
    const sync = (e: StorageEvent) => { if (!e.key || e.key === key) setChoice(saved()) }
    media.addEventListener('change', update)
    window.addEventListener('storage', sync)
    return () => { media.removeEventListener('change', update); window.removeEventListener('storage', sync) }
  }, [])
  const mode = choice === 'static' ? 'static' : systemReduce || choice === 'reduced' ? 'reduced' : 'standard'
  useEffect(() => { document.documentElement.dataset.motion = mode }, [mode])
  return { choice, reduced: mode !== 'standard', choose(value: MotionChoice) {
    setChoice(value)
    try { localStorage.setItem(key, value) } catch { /* In-memory choice still applies. */ }
  } }
}
