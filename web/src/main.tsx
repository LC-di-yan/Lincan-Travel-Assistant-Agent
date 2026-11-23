import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/globals.css'
import App from './App'
import { ensureIdentity } from './api/client'
import { LEGACY_CONVERSATION } from './api/conversations'
import { RouteBeacon } from './components/Illustrations/RouteBeacon'
import { useChatStore } from './store/chatStore'

const root = createRoot(document.getElementById('root')!)
const renderConnection = (failed: boolean) => root.render(
  <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-4 bg-paper text-ink">
    <span className="brand-mark"><RouteBeacon size={26} /></span>
    <p role="status">{failed ? '未能建立安全会话，请检查网络后重试。' : '正在建立安全会话…'}</p>
    {failed && <button className="deck-action" onClick={() => window.location.reload()}>重新连接</button>}
  </div>,
)

const waiting = window.setTimeout(() => renderConnection(false), 150)
void ensureIdentity().then((identity) => {
  // Local storage is only a resume hint; the signed browser identity owns the session.
  const previousUser = localStorage.getItem('aligo_user_id')
  const savedId = previousUser === identity.user_id ? localStorage.getItem('aligo_session_id') : null
  const previousSession = savedId && (savedId === LEGACY_CONVERSATION || /^[\w-]{1,32}$/.test(savedId)) ? savedId : null
  const store = useChatStore.getState()
  store.setUserId(identity.user_id)
  store.setSessionId(previousSession)
  root.render(<StrictMode><App previousSession={previousSession} /></StrictMode>)
}).catch(() => renderConnection(true)).finally(() => window.clearTimeout(waiting))
