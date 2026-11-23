import { useState, Component, type ReactNode, useEffect, useRef, lazy, Suspense } from 'react'
import { X } from 'lucide-react'
import { useMotionPolicy } from './hooks/useMotionPolicy'
import { SurfaceDialog } from './components/Layout/SurfaceDialog'
import { DeferredRegion } from './components/Layout/DeferredRegion'
import { useTheme } from './hooks/useTheme'
import { Header } from './components/Layout/Header'
import { ChatPanel } from './components/Chat/ChatPanel'
import { createSession } from './api/client'
import { LEGACY_CONVERSATION } from './api/conversations'
import { useChatStore } from './store/chatStore'
import { personalCapabilities } from './api/personal'
import { useConversationNavigation } from './hooks/useConversationNavigation'

const PersonalCenter = lazy(() => import('./components/Personal/PersonalCenter'))
const ConversationSidebar = lazy(() => import('./components/Chat/ConversationSidebar').then(m => ({ default: m.ConversationSidebar })))
const Sidebar = lazy(() => import('./components/Sidebar/Sidebar').then(m => ({ default: m.Sidebar })))

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
          <p className="max-w-md text-sm leading-6 text-ink-2">可以刷新页面后重试。已保存的对话不会被删除。</p>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            className="mt-2 h-11 rounded-input bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-hover"
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App({ previousSession }: { previousSession: string | null }) {
  const { dark, toggle } = useTheme()
  const motion = useMotionPolicy()
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 1280px)').matches)
  const [panel, setPanel] = useState<'auto' | 'history' | 'archive' | 'closed'>('auto')
  const hasMessages = useChatStore(s => s.messages.length > 0)
  const sessionId = useChatStore((s) => s.sessionId)
  const setSessionId = useChatStore((s) => s.setSessionId)
  const {
    open: openConversation, startNew, view, pending: switching, problem, loadOlder, olderBusy, olderError,
  } = useConversationNavigation(Boolean(previousSession))
  const [personalEnabled, setPersonalEnabled] = useState(false)
  const [personalChecked, setPersonalChecked] = useState(false)
  const [location, setLocation] = useState(() => window.location.hash.slice(1))
  const inPersonal = location === '/personal' || location.startsWith('/personal/')
  const displayed = inPersonal ? null : panel === 'auto' ? (wide && hasMessages ? 'history' : null) : panel === 'closed' ? null : panel
  const previousPersonal = useRef(inPersonal)
  useEffect(() => {
    if (previousPersonal.current && !inPersonal) document.querySelector<HTMLElement>('.deck-brand')?.focus({ preventScroll: true })
    previousPersonal.current = inPersonal
  }, [inPersonal])
  const working = useChatStore((s) => s.isProcessing)

  useEffect(() => {
    const update = () => {
      const route = window.location.hash.slice(1)
      setLocation(route)
      if (route.startsWith('/personal')) setPanel('auto')
    }
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])

  useEffect(() => {
    let stopped = false
    personalCapabilities().then((caps) => {
      if (!stopped) setPersonalEnabled(caps.enabled)
    }).catch(() => {}).finally(() => {
      if (!stopped) setPersonalChecked(true)
    })
    return () => { stopped = true }
  }, [])

  useEffect(() => {
    if (previousSession) void openConversation(previousSession, true)
  }, [openConversation, previousSession])

  // The current empty conversation is allocated separately from the owner's history.
  useEffect(() => {
    if (sessionId || switching) return
    let cancelled = false
    createSession()
      .then((data) => {
        if (!cancelled && data?.session_id && !useChatStore.getState().sessionId) setSessionId(data.session_id)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [sessionId, setSessionId, switching])

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1280px)')
    const resize = (event: MediaQueryListEvent) => { setWide(event.matches); setPanel('auto') }
    media.addEventListener('change', resize)
    return () => media.removeEventListener('change', resize)
  }, [])

  const togglePanel = (next: 'history' | 'archive') => setPanel(displayed === next ? 'closed' : next)
  const closePanel = () => setPanel('closed')
  const openHistory = (id: string) => {
    if (!wide) closePanel()
    void openConversation(id)
  }
  const newChat = () => {
    if (!wide) closePanel()
    else if (displayed === 'history') setPanel('history')
    void startNew()
  }
  const historyProps = { activeId: sessionId, navigating: switching, working, onSelect: openHistory }
  const archive = <section id="trip-archive" className="archive-panel" aria-label="行程档案">
    <div className="archive-heading"><h2>行程档案</h2>
      <button type="button" autoFocus={!wide} aria-label="关闭行程档案" onClick={closePanel} className="nav-tool nav-icon"><X size={18} /></button>
    </div><DeferredRegion label="行程档案">
      <Sidebar personalAvailable={personalEnabled} />
    </DeferredRegion>
  </section>

  return (
    <ErrorBoundary>
      <div className="flex h-[100dvh] flex-col bg-paper">
        <Header
          dark={dark}
          toggle={toggle}
          motion={motion.choice}
          onMotion={motion.choose}
          hasMessages={hasMessages}
          sidebarOpen={displayed === 'archive'}
          onToggleSidebar={() => togglePanel('archive')}
          personalAvailable={personalEnabled}
          inPersonal={inPersonal}
          historyOpen={displayed === 'history'}
          onToggleHistory={() => togglePanel('history')}
          onNewConversation={newChat}
          switching={switching}
        />
        {inPersonal && <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {working && <div role="status" className="border-b border-rule bg-paper-sunken px-4 py-2 text-sm text-ink-2">
            助手仍在生成回复 · <a className="font-semibold text-accent underline" href="#/">返回对话查看</a>
          </div>}
          {personalEnabled
            ? <Suspense fallback={<p className="p-6 text-ink-2" role="status">正在加载个人中心…</p>}>
                <PersonalCenter path={location} />
              </Suspense>
            : <div className="p-6 text-ink">
                <p role="status">{personalChecked ? '当前站点尚未开放个人中心。' : '正在检查个人中心是否可用…'}</p>
                <a href="#/" className="mt-2 inline-block text-accent underline">返回对话</a>
              </div>}
        </div>}
        <div hidden={inPersonal} className={inPersonal ? 'hidden' : 'relative flex min-h-0 flex-1 overflow-hidden'}>
          {displayed === 'history' && (wide
            ? <aside className="w-64 shrink-0 border-r border-rule">
                <DeferredRegion label="聊天记录">
                  <ConversationSidebar {...historyProps} />
                </DeferredRegion>
              </aside>
            : <SurfaceDialog side="left" label="聊天记录" onClose={closePanel}>
                <DeferredRegion label="聊天记录">
                  <ConversationSidebar {...historyProps} onNew={newChat} onClose={closePanel} />
                </DeferredRegion>
              </SurfaceDialog>)}
          <div className="flex min-w-0 flex-1 flex-col" aria-busy={switching}>
            {switching && <p role="status" className="border-b border-rule bg-paper-sunken px-4 py-2 text-sm text-ink-2">正在打开对话…</p>}
            {problem && <div role="status" className="flex flex-wrap items-center gap-2 border-b border-rule bg-paper-sunken px-4 text-xs text-ink-2">
              <span>{problem.message}</span>
              <button type="button" className="min-h-11 font-semibold text-accent underline" onClick={problem.retry}>重试</button>
            </div>}
            <ChatPanel
              key={view.epoch}
              readOnly={sessionId === LEGACY_CONVERSATION}
              switching={switching}
              reducedMotion={motion.reduced}
              visible={!inPersonal}
              onStartNew={newChat}
              loadOlder={view.nextBefore === null ? undefined : loadOlder}
              olderBusy={olderBusy}
              olderError={olderError}
            />
          </div>

          {displayed === 'archive' && (wide
            ? <aside className="w-80 shrink-0 border-l border-rule">{archive}</aside>
            : <SurfaceDialog side="right" label="行程档案" onClose={closePanel}>{archive}</SurfaceDialog>)}
        </div>
      </div>
    </ErrorBoundary>
  )
}
