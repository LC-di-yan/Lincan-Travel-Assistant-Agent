import { Sun, Moon } from 'lucide-react'

export function ThemeToggle({ dark, toggle }: { dark: boolean; toggle: () => void }) {
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? '切换到亮色模式' : '切换到暗色模式'}
      title={dark ? '切换到亮色' : '切换到暗色'}
      className="flex h-11 w-11 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
    >
      {dark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
    </button>
  )
}
