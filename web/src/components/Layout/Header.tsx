import { lazy, useState } from 'react'
import { History, PanelsRightBottom, SlidersHorizontal, Plus, CircleUserRound, Compass } from 'lucide-react'
import type { MotionChoice } from '../../hooks/useMotionPolicy'
import { RouteBeacon } from '../Illustrations/RouteBeacon'
import { ThemeToggle } from './ThemeToggle'
import { SurfaceDialog } from './SurfaceDialog'
import { DeferredRegion } from './DeferredRegion'

const TTSSettings = lazy(() => import('./TTSSettings').then(m => ({ default: m.TTSSettings })))

interface Props {
  dark: boolean; toggle: () => void
  motion: MotionChoice; onMotion: (value: MotionChoice) => void
  sidebarOpen: boolean; onToggleSidebar: () => void
  personalAvailable: boolean; inPersonal: boolean; hasMessages: boolean
  historyOpen: boolean; onToggleHistory: () => void
  onNewConversation: () => void; switching: boolean
}

export function Header({ dark, toggle, motion, onMotion, sidebarOpen, onToggleSidebar, personalAvailable,
  inPersonal, hasMessages, historyOpen, onToggleHistory, onNewConversation, switching }: Props) {
  const [settings, setSettings] = useState(false)
  return <>
    <header className="deck-header"><div className="masthead">
      <a href="#/" className="deck-brand" aria-label={inPersonal ? 'ALIGO，返回航图台' : 'ALIGO 首页'}>
        <span className="brand-mark"><RouteBeacon size={26} /></span><strong>ALIGO</strong>
      </a>
      <nav aria-label="工作区导航" className="desk-nav" data-personal={inPersonal}>
        <a href="#/" className="desk-link work-link" aria-label={inPersonal ? '返回对话' : '差旅航图台'}
          aria-current={!inPersonal ? 'page' : undefined}><Compass size={16} /> <span>{inPersonal ? '返回对话' : '航图台'}</span></a>
        {personalAvailable && <a href="#/personal" className="desk-link personal-link" aria-label="个人中心"
          aria-current={inPersonal ? 'page' : undefined} title="个人中心"><CircleUserRound size={17} /> <span>个人中心</span></a>}
      </nav>
      <div className="mast-actions">
        {!inPersonal && <>
          {hasMessages && <button type="button" className="nav-tool nav-new" onClick={onNewConversation} disabled={switching}
            aria-label="新对话" title="新对话"><Plus size={17} /><span>新对话</span></button>}
          <button type="button" className="nav-tool" onClick={onToggleHistory} aria-expanded={historyOpen}
            aria-controls={historyOpen ? 'conversation-history' : undefined} title="聊天记录"
            aria-label={historyOpen ? '收起聊天记录' : '展开聊天记录'}><History size={17} /><span>聊天记录</span></button>
          <button type="button" className="nav-tool" onClick={onToggleSidebar} aria-expanded={sidebarOpen}
            aria-controls={sidebarOpen ? 'trip-archive' : undefined} title="行程档案"
            aria-label={sidebarOpen ? '收起行程档案' : '展开行程档案'}><PanelsRightBottom size={17} /><span>行程档案</span></button>
        </>}
        <div className="mast-appearance"><ThemeToggle dark={dark} toggle={toggle} /></div>
        <button type="button" className="nav-tool nav-icon" onClick={() => setSettings(true)} aria-haspopup="dialog"
          title="显示与语音设置" aria-label="显示与语音设置"><SlidersHorizontal size={17} /></button>
      </div>
    </div></header>
    {settings && <SurfaceDialog label="显示与语音设置" onClose={() => setSettings(false)}>
      <DeferredRegion label="显示与语音设置">
        <TTSSettings onClose={() => setSettings(false)} dark={dark} toggle={toggle} motion={motion} onMotion={onMotion} />
      </DeferredRegion>
    </SurfaceDialog>}
  </>
}
