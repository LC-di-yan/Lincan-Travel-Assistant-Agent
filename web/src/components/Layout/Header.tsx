import { Trash2, PanelRightOpen, PanelRightClose } from 'lucide-react'
import { ThemeToggle } from './ThemeToggle'
import { useChatStore } from '../../store/chatStore'

export function Header({ dark, toggle, sidebarOpen, onToggleSidebar }: {
  dark: boolean
  toggle: () => void
  sidebarOpen: boolean
  onToggleSidebar: () => void
}) {
  const clearChat = useChatStore((s) => s.clearChat)

  return (
    <header className="h-14 flex items-center justify-between px-5 glass"
      style={{ borderBottom: '1px solid var(--border)' }}>
      <div className="flex items-center gap-2.5">
        <button onClick={clearChat} className="flex items-center gap-2.5 cursor-pointer" title="回到首页">
          <img src="/images/logo.png" alt="Aligo" className="w-8 h-8 rounded-xl object-cover" />
          <span className="font-bold text-lg text-gradient">Aligo</span>
        </button>
        <span className="hidden md:inline text-xs text-[var(--text-muted)] font-medium tracking-wide">智能旅行助手</span>
      </div>
      <div className="flex items-center gap-1.5">
        <button onClick={clearChat}
          className="p-2 rounded-xl transition-all hover:bg-[var(--bg-tertiary)] hover:scale-105 active:scale-95"
          title="清空对话">
          <Trash2 size={15} className="text-[var(--text-muted)]" />
        </button>
        <button onClick={onToggleSidebar}
          className="p-2 rounded-xl transition-all hover:bg-[var(--bg-tertiary)] hover:scale-105 active:scale-95"
          title={sidebarOpen ? '收起侧栏' : '展开侧栏'}>
          {sidebarOpen
            ? <PanelRightClose size={15} className="text-[var(--text-muted)]" />
            : <PanelRightOpen size={15} className="text-[var(--text-muted)]" />}
        </button>
        <ThemeToggle dark={dark} toggle={toggle} />
      </div>
    </header>
  )
}
