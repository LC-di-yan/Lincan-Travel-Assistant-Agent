import { useState, useEffect } from 'react'

const STORAGE_KEY = 'aligo-theme'

function getInitialDark(): boolean {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return saved === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch {
    return false
  }
}

export function useTheme() {
  const [dark, setDark] = useState(getInitialDark)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => {
      try {
        if (!localStorage.getItem(STORAGE_KEY)) setDark(e.matches)
      } catch {
        /* ignore */
      }
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const toggle = () => {
    setDark((d) => {
      const next = !d
      try {
        localStorage.setItem(STORAGE_KEY, next ? 'dark' : 'light')
      } catch {
        /* ignore */
      }
      return next
    })
  }

  return { dark, toggle }
}
