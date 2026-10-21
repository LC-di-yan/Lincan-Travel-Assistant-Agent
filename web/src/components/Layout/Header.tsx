import { useState } from 'react'
import { PanelRightOpen, PanelRightClose, Volume2, Plus } from 'lucide-react'
import { ThemeToggle } from './ThemeToggle'
import { TTSSettings } from './TTSSettings'
import { ConfirmDialog } from './ConfirmDialog'
import { useChatStore } from '../../store/chatStore'

export function Header({ dark, toggle, sidebarOpen, onToggleSidebar }: {
  dark: boolean
  toggle: () => void
  sidebarOpen: boolean
  onToggleSidebar: () => void
}) {
  const clearChat = useChatStore((s) => s.clearChat)
  const messages = useChatStore((s) => s.messages)
  const [ttsOpen, setTtsOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const requestClear = () => {
    if (messages.length === 0) {
      clearChat()
      return
    }
    setConfirmOpen(true)
  }

  return (
    <>
      <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-rule bg-paper px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={requestClear}
            className="flex min-w-0 items-center gap-2.5 rounded-[2px] text-left"
            title="新对话"
          >
            <span
              aria-hidden="true"
              className="flex h-6 w-6 flex-shrink-0 -rotate-3 items-center justify-center rounded-[2px] border-[1.5px] border-accent font-mono text-[11px] font-bold leading-none text-accent"
            >
              A
            </span>
            <span className="truncate text-[15px] font-bold tracking-[0.16em] text-ink">ALIGO</span>
            <span className="hidden text-[11px] tracking-[0.08em] text-ink-3 sm:inline">差旅文件</span>
          </button>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={requestClear}
            className="mr-1 hidden h-9 items-center gap-1.5 rounded-[2px] border border-rule-strong px-3 text-xs font-semibold text-ink hover:bg-paper-sunken sm:flex"
          >
            <Plus size={14} aria-hidden="true" />
            新对话
          </button>

          <button
            type="button"
            onClick={requestClear}
            aria-label="新对话"
            title="新对话"
            className="flex h-11 w-11 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink sm:hidden"
          >
            <Plus size={18} aria-hidden="true" />
          </button>

          <button
            type="button"
            aria-label="语音设置"
            title="语音设置"
            onClick={() => setTtsOpen(true)}
            className="flex h-11 w-11 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
          >
            <Volume2 size={18} aria-hidden="true" />
          </button>

          <button
            type="button"
            aria-label={sidebarOpen ? '收起行程档案' : '展开行程档案'}
            aria-expanded={sidebarOpen}
            title={sidebarOpen ? '收起侧栏' : '展开侧栏'}
            onClick={onToggleSidebar}
            className="flex h-11 w-11 items-center justify-center rounded-[2px] text-ink-3 hover:bg-paper-sunken hover:text-ink"
          >
            {sidebarOpen
              ? <PanelRightClose size={18} aria-hidden="true" />
              : <PanelRightOpen size={18} aria-hidden="true" />}
          </button>

          <ThemeToggle dark={dark} toggle={toggle} />
        </div>
      </header>

      <TTSSettings open={ttsOpen} onClose={() => setTtsOpen(false)} />

      <ConfirmDialog
        open={confirmOpen}
        title="删除当前对话？"
        description="这会清空当前会话的消息。偏好、历史和费用记录不会删除。"
        confirmLabel="删除"
        danger
        onConfirm={clearChat}
        onClose={() => setConfirmOpen(false)}
      />
    </>
  )
}
