import { useState, useEffect, useLayoutEffect, useRef, useCallback, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowUp, Square, Mic, AlignLeft } from 'lucide-react'
import { useSpeechRecognition } from '../../hooks/useSpeechRecognition'
import { useChatStore } from '../../store/chatStore'
import { RouteBeacon } from '../Illustrations/RouteBeacon'
import { ActionButton } from '../Layout/ActionButton'
import { BriefExamples } from './BriefHero'

const STOP_TAP_GUARD_MS = 350

interface InputProps {
  onSend: (text: string) => void
  onCancel: () => void
  disabled: boolean
  blocked: boolean
  offline: boolean
  brief: boolean
  examples: boolean
  notice?: ReactNode
  visible: boolean
}

export function InputBar({ onSend, onCancel, disabled, blocked, offline, brief, examples, notice, visible }: InputProps) {
  const text = useChatStore(s => s.composerDrafts.get(s.sessionId) ?? '')
  const setText = useChatStore(s => s.updateComposerDraft)
  const [invalid, setInvalid] = useState(false)
  const [previousDraft, setPreviousDraft] = useState<string | null>(null)
  const [exampleApplied, setExampleApplied] = useState(false)
  const [speechIssue, setSpeechIssue] = useState('')
  const [composer, setComposer] = useState<HTMLFormElement | null>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const pressedAction = useRef<'stop' | 'send' | null>(null)
  const lastPointerAction = useRef<{ action: 'stop' | 'send'; time: number } | null>(null)
  const edit = useCallback((value: string) => {
    setText(value); setInvalid(false); setPreviousDraft(null); setExampleApplied(false); setSpeechIssue('')
  }, [setText])
  useEffect(() => {
    if (disabled) return
    let active = true
    const adoptPrompt = () => {
      const { draftPrompt, setDraftPrompt } = useChatStore.getState()
      if (!active || !draftPrompt) return
      setDraftPrompt(null)
      setText(old => old ? old + '\n' + draftPrompt : draftPrompt)
      setInvalid(false)
      setPreviousDraft(null); setExampleApplied(false); setSpeechIssue('')
    }
    const unsubscribe = useChatStore.subscribe(adoptPrompt)
    queueMicrotask(adoptPrompt)
    return () => { active = false; unsubscribe() }
  }, [disabled, setText])
  const appendSpeech = useCallback((value: string) => {
    if (useChatStore.getState().isProcessing) return
    setText(previous => previous + value); setInvalid(false); setPreviousDraft(null); setExampleApplied(false); setSpeechIssue('')
  }, [setText])
  const { isListening, isSupported, interimText, startListening, stopListening } = useSpeechRecognition({
    lang: 'zh-CN', continuous: false, interimResults: true, onFinal: appendSpeech, onIssue: setSpeechIssue,
  })
  useEffect(() => {
    if ((disabled || blocked || !visible) && isListening) stopListening()
  }, [blocked, disabled, visible, isListening, stopListening])
  const displayText = isListening && interimText ? text + interimText : text
  useLayoutEffect(() => {
    const el = taRef.current
    if (!el || !visible) return
    el.style.height = '0px'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, [displayText, brief, visible])

  const submit = () => {
    if (disabled || blocked || offline || !navigator.onLine || useChatStore.getState().isProcessing) return
    if (!text.trim()) { setInvalid(true); taRef.current?.focus(); return }
    onSend(text.trim())
    edit('')
    if (isListening) stopListening()
  }
  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return
    e.preventDefault()
    if (!e.repeat) submit()
  }
  const chooseExample = (value: string) => {
    if (text !== value) setPreviousDraft(text.trim() ? text : null)
    setExampleApplied(true); setSpeechIssue(''); setText(value); setInvalid(false)
    taRef.current?.focus()
  }
  return <>
    <div className="composer-cell">
      {notice}
      <form ref={setComposer} className="flight-composer" data-listening={isListening || undefined}
        onSubmit={event => { event.preventDefault(); submit() }}>
        {brief && <div className="composer-title"><label htmlFor="flight-request"><AlignLeft size={16} aria-hidden="true" /> 行前简报</label>
          <span>可编辑</span></div>}
        <textarea id="flight-request" ref={taRef} value={displayText} onChange={e => edit(e.target.value)}
          onKeyDown={handleKey} aria-label="输入消息" aria-invalid={invalid || undefined}
          aria-describedby={invalid || offline || speechIssue ? 'compose-hint' : undefined} rows={brief ? 2 : 1} disabled={blocked}
          placeholder={isListening ? '正在聆听…' : brief ? '例如：明天从北京去上海出差 3 天，预算 2000 元。' : '继续补充你的差旅需求…'} />
        <div className="composer-tools">
          {isSupported && <button type="button" className="mic-control" onClick={() => { setSpeechIssue(''); if (isListening) stopListening(); else startListening() }}
            aria-pressed={isListening} disabled={(disabled || blocked || offline) && !isListening}
            aria-label={isListening ? '停止语音输入' : '语音输入'} title={isListening ? '停止语音输入' : '语音输入'}>
            <Mic size={18} strokeWidth={1.65} aria-hidden="true" />{brief && <span>{isListening ? '正在聆听' : '语音输入'}</span>}
          </button>}
          <span className="compose-keys" aria-hidden="true">{brief ? 'Enter 发送' : ''}</span>
          <ActionButton intent={disabled ? 'stop' : 'primary'} type={disabled ? 'button' : 'submit'} magnetic={disabled ? null : composer} magneticPull={brief ? 10 : 7}
            disabled={!disabled && (blocked || offline || (!brief && !text.trim()))}
            aria-label={disabled ? '停止生成' : brief ? '开始规划' : '发送消息'}
            icon={disabled ? <Square size={13} fill="currentColor" /> : brief ? <RouteBeacon size={19} /> : <ArrowUp size={17} />}
            onPointerDown={() => { pressedAction.current = disabled ? 'stop' : 'send' }}
            onPointerCancel={() => { pressedAction.current = null }}
            onKeyDown={event => {
              if (event.repeat && (event.key === 'Enter' || event.key === ' ')) event.preventDefault()
            }}
            onClick={event => {
              const pointer = event.detail > 0
              const pressed = pressedAction.current
              pressedAction.current = null
              const action = disabled ? 'stop' : 'send'
              const now = performance.now()
              const previous = lastPointerAction.current
              const repeated = previous && previous.action !== action &&
                (event.detail > 1 || (action === 'send' && now - previous.time < STOP_TAP_GUARD_MS))
              if (pointer && ((pressed && pressed !== action) || repeated || (!pressed && event.detail > 1))) {
                // A repeated press at the same position must not activate a different action.
                event.preventDefault()
                if (pressed === 'stop') lastPointerAction.current = { action: 'stop', time: now }
                return
              }
              lastPointerAction.current = pointer ? { action, time: now } : null
              if (disabled) {
                // Cancelling synchronously turns this same button into a submit button.
                event.preventDefault()
                if (!pointer && !text.trim()) taRef.current?.focus({ preventScroll: true })
                onCancel()
              }
            }}>
            {disabled ? '停止' : brief ? '开始规划' : '发送'}
          </ActionButton>
        </div>
      </form>
      {(invalid || offline || exampleApplied || speechIssue || isListening || !brief) && <div className="composer-foot">
        <span role="status" id="compose-hint">{offline ? '当前离线，联网后可手动发送。' : invalid ? '先写下差旅需求，或从下方选一个示例。' :
          speechIssue ? speechIssue : isListening ? '正在聆听，点击麦克风可停止。' : exampleApplied ? '已填入示例，未发送。' : '请核对关键时间、价格与来源。'}</span>
        {previousDraft !== null && <button type="button" onClick={() => { edit(previousDraft); taRef.current?.focus() }}>撤销替换</button>}
        {!brief && <span className="compose-keys">Shift + Enter 换行</span>}
      </div>}
    </div>
    {brief && examples && <BriefExamples onChoose={chooseExample} />}
  </>
}
