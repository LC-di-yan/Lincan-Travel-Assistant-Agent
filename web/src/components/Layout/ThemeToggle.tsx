import { Sun, Moon } from 'lucide-react'

export function ThemeToggle({ dark, toggle }: { dark: boolean; toggle: () => void }) {
  return (
    <button
      onClick={toggle}
      className="p-2 rounded-xl transition-all duration-300 hover:bg-[var(--bg-tertiary)] hover:scale-110 active:scale-95"
      title={dark ? '切换亮色' : '切换暗色'}
    >
      <div className="relative w-[18px] h-[18px]">
        <Sun
          size={18}
          className={`absolute inset-0 text-[var(--warning)] transition-all duration-300 ${
            dark ? 'opacity-100 rotate-0' : 'opacity-0 -rotate-90'
          }`}
        />
        <Moon
          size={18}
          className={`absolute inset-0 text-[var(--text-secondary)] transition-all duration-300 ${
            dark ? 'opacity-0 rotate-90' : 'opacity-100 rotate-0'
          }`}
        />
      </div>
    </button>
  )
}
