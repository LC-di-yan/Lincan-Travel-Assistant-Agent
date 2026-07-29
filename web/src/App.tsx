import { useState, Component, type ReactNode, useEffect } from 'react'
import { useTheme } from './hooks/useTheme'
import { Header } from './components/Layout/Header'
import { ChatPanel } from './components/Chat/ChatPanel'
import { Sidebar } from './components/Sidebar/Sidebar'

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="h-screen flex flex-col items-center justify-center gap-4"
          style={{ backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
          <img src="/images/illustrations/error.svg" alt="错误" className="w-40 h-auto opacity-80 mb-2" />
          <p className="text-lg font-bold text-[var(--error)]">页面出错了</p>
          <p className="text-sm text-[var(--text-muted)]">{this.state.error.message}</p>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            className="px-4 py-2 rounded-xl text-sm text-white"
            style={{ background: 'linear-gradient(135deg, var(--accent), #8b5cf6)' }}>
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function useIsMobile() {
  const [mobile, setMobile] = useState(window.innerWidth < 768)
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

  useEffect(() => {
    if (isMobile) setSidebarOpen(false)
  }, [isMobile])

  const handleToggleSidebar = () => setSidebarOpen((v) => !v)
  const closeSidebar = () => setSidebarOpen(false)

  const sidebarContent = (
    <div className="h-full">
      <Sidebar />
    </div>
  )

  return (
    <ErrorBoundary>
      <div className="h-screen flex flex-col" style={{ backgroundColor: 'var(--bg-primary)' }}>
        <Header
          dark={dark}
          toggle={toggle}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={handleToggleSidebar}
        />
        <div className="flex-1 flex overflow-hidden relative">
          <div className="flex-1 flex flex-col min-w-0" onClick={isMobile && sidebarOpen ? closeSidebar : undefined}>
            <ChatPanel />
          </div>

          {/* Desktop: side-by-side sidebar */}
          {!isMobile && (
            <div
              className="border-l flex-shrink-0 overflow-hidden transition-all duration-300"
              style={{
                borderColor: 'var(--border)',
                backgroundColor: 'var(--bg-primary)',
                width: sidebarOpen ? '18rem' : '0',
              }}
            >
              <div className="w-72 h-full">
                {sidebarContent}
              </div>
            </div>
          )}

          {/* Mobile: overlay drawer */}
          {isMobile && (
            <>
              {sidebarOpen && (
                <div
                  className="fixed inset-0 z-40 bg-black/40 transition-opacity duration-300"
                  onClick={closeSidebar}
                />
              )}
              <div
                className="fixed right-0 top-0 bottom-0 z-50 transition-transform duration-300 shadow-lg"
                style={{
                  backgroundColor: 'var(--bg-primary)',
                  borderLeft: '1px solid var(--border)',
                  width: '18rem',
                  transform: sidebarOpen ? 'translateX(0)' : 'translateX(100%)',
                }}
              >
                {sidebarContent}
              </div>
            </>
          )}
        </div>
      </div>
    </ErrorBoundary>
  )
}
