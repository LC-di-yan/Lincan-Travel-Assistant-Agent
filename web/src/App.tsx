import { useState, Component, type ReactNode, useEffect, useRef } from 'react'
import { useTheme } from './hooks/useTheme'
import { Header } from './components/Layout/Header'
import { ChatPanel } from './components/Chat/ChatPanel'
import { Sidebar } from './components/Sidebar/Sidebar'
import { createSession } from './api/client'
import { useChatStore } from './store/chatStore'

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-[100dvh] flex flex-col items-center justify-center gap-4 bg-paper px-6 text-center">
          <div className="font-mono text-[11px] tracking-[0.16em] text-accent">ALIGO / ERROR</div>
          <p className="font-display text-2xl text-ink">页面出错了</p>
          <p className="max-w-md text-sm leading-6 text-ink-2">{this.state.error.message}</p>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            className="mt-2 h-11 rounded-[2px] bg-accent px-4 text-sm font-semibold text-paper hover:bg-accent-hover"
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const onResize = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return mobile
}

export default function App() {
  const { dark, toggle } = useTheme()
  const isMobile = useIsMobile()
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768)
  const drawerRef = useRef<HTMLDivElement>(null)
  const sessionId = useChatStore((s) => s.sessionId)
  const setSessionId = useChatStore((s) => s.setSessionId)

  // 首次打开就拿到 session，侧栏的偏好/历史/费用才能读到数据；
  // 刷新后沿用 localStorage 里的 id，后端会按该 id 重建。
  useEffect(() => {
    if (sessionId) return
    let cancelled = false
    createSession(useChatStore.getState().userId)
      .then((data) => {
        if (!cancelled && data?.session_id) setSessionId(data.session_id)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [sessionId, setSessionId])

  useEffect(() => {
    if (isMobile) setSidebarOpen(false)
  }, [isMobile])

  useEffect(() => {
    if (!isMobile || !sidebarOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSidebarOpen(false)
        return
      }
      if (e.key !== 'Tab') return
      const nodes = drawerRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (!nodes || nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    drawerRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = prev
    }
  }, [isMobile, sidebarOpen])

  const handleToggleSidebar = () => setSidebarOpen((v) => !v)
  const closeSidebar = () => setSidebarOpen(false)

  return (
    <ErrorBoundary>
      <div className="flex h-[100dvh] flex-col bg-paper">
        <Header
          dark={dark}
          toggle={toggle}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={handleToggleSidebar}
        />
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <div className="flex min-w-0 flex-1 flex-col">
            <ChatPanel />
          </div>

          {!isMobile && (
            <div
              className="flex-shrink-0 overflow-hidden border-l border-rule transition-[width] duration-200"
              style={{ width: sidebarOpen ? '20rem' : '0' }}
              aria-hidden={!sidebarOpen}
            >
              <div className="h-full w-80">
                {sidebarOpen && <Sidebar />}
              </div>
            </div>
          )}

          {isMobile && sidebarOpen && (
            <>
              <button
                type="button"
                aria-label="关闭侧栏"
                className="fixed inset-0 z-40 bg-black/35"
                onClick={closeSidebar}
              />
              <div
                ref={drawerRef}
                role="dialog"
                aria-modal="true"
                aria-label="行程档案"
                tabIndex={-1}
                className="fixed right-0 top-0 bottom-0 z-50 w-80 max-w-[86vw] border-l border-rule bg-paper shadow-lg outline-none"
              >
                <Sidebar />
              </div>
            </>
          )}
        </div>
      </div>
    </ErrorBoundary>
  )
}
