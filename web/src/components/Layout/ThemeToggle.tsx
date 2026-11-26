import { Sun, Moon } from 'lucide-react'
import type { ThemeTriggerEvent } from '../effects/themeRevealCore'

export function ThemeToggle({ dark, toggle }: { dark: boolean; toggle: (event?: ThemeTriggerEvent) => void }) {
  return (
    <button
      type="button"
      onClick={(event) => toggle({
        clientX: event.clientX,
        clientY: event.clientY,
        detail: event.detail,
        currentTarget: event.currentTarget,
      })}
      aria-label={dark ? '切换到亮色模式' : '切换到暗色模式'}
      title={dark ? '切换到亮色' : '切换到暗色'}
      className="nav-tool nav-icon"
    >
      {dark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
    </button>
  )
}
