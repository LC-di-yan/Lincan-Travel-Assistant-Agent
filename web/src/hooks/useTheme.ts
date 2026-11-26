import { useCallback, useEffect, useRef, useState } from 'react'
import { revealThemeChange, type ThemeTriggerEvent } from '../components/effects/themeRevealCore'

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
  // 连点时上一跳的提交可能还没落地，用它把点击串起来，避免每次都算出同一个目标值；
  // 提交真正落地后归还给 DOM（只由最新一次点击归还，避免覆盖更新的目标）。
  const pendingRef = useRef<boolean | null>(null)
  const seqRef = useRef(0)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#101b20' : '#f5f4ec')
  }, [dark])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => {
      try {
        if (!localStorage.getItem(STORAGE_KEY)) {
          pendingRef.current = null
          setDark(e.matches)
        }
      } catch {
        /* ignore */
      }
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // 圆形揭示：类名与存储在过渡回调里同步提交，新快照才是新主题。
  const toggle = useCallback((event?: ThemeTriggerEvent) => {
    const root = document.documentElement
    const current = pendingRef.current ?? root.classList.contains('dark')
    const next = !current
    const seq = ++seqRef.current
    pendingRef.current = next
    revealThemeChange({
      target: root,
      event: event ?? null,
      fromClick: true,
      apply: () => {
        root.classList.toggle('dark', next)
        try {
          localStorage.setItem(STORAGE_KEY, next ? 'dark' : 'light')
        } catch {
          /* ignore */
        }
        document.querySelector('meta[name="theme-color"]')?.setAttribute('content', next ? '#101b20' : '#f5f4ec')
        if (seqRef.current === seq) pendingRef.current = null
        setDark(next)
      },
    })
  }, [])

  return { dark, toggle }
}
