import { useRef, useEffect, useState } from 'react'
import { useChatStore } from '../../store/chatStore'
import { sendChatMessage, createSession, abortActiveRequest } from '../../api/client'
import { uid } from '../../store/chatStore'
import { MessageBubble } from './MessageBubble'
import { RouteStrip } from './RouteStrip'
import { InputBar } from './InputBar'
import { ArrowUpRight } from 'lucide-react'
import { useTTSPlayer } from '../../hooks/useTTSPlayer'
import { useTTSPrefs } from '../../hooks/useTTSPrefs'
import { useNarrate } from '../../hooks/useNarrate'
import { extractTTSTexts } from '../../utils/ttsText'
import type { OrchestrationResult } from '../../api/types'

// 简单意图：文案短且结构化，直接用 extractTTSTexts，不调 LLM
const FAST_PATH_INTENTS = new Set([
  'expense_tracking',
  'preference',
  'translation',
  'currency_converter',
  'currency_conversion',
])

// 进度播报节流参数
const PROGRESS_MIN_INTERVAL_MS = 5000  // 两次进度播报最小间隔
const PROGRESS_MAX_COUNT = 3           // 单任务最多进度播报次数
const LONG_TASK_THRESHOLD_MS = 4000    // 任务超过 4s 才触发进度播报

// 简单意图不触发进度播报（任务太短）
const PROGRESS_SKIP_INTENTS = new Set([
  'expense_tracking',
  'preference',
  'translation',
  'currency_converter',
  'currency_conversion',
  'memory_query',
])

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages)
  const isProcessing = useChatStore((s) => s.isProcessing)
  const currentIntention = useChatStore((s) => s.currentIntention)
  const currentAgents = useChatStore((s) => s.currentAgents)
  const runningAgents = useChatStore((s) => s.runningAgents)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [showJump, setShowJump] = useState(false)
  const [offline, setOffline] = useState(() => !navigator.onLine)
  // 当前在途请求对应的 AI 消息 id（供「停止生成」精确定位）
  const activeAssistantIdRef = useRef<string | null>(null)
  const { play } = useTTSPlayer()
  const { prefs } = useTTSPrefs()
  const { narrate, narrateProgress } = useNarrate()
  const autoPlayRef = useRef(prefs.autoPlay)
  useEffect(() => { autoPlayRef.current = prefs.autoPlay }, [prefs.autoPlay])

  // 进度播报节流状态（用 ref 避免 re-render）
  const taskStartRef = useRef<number>(0)
  const lastProgressTimeRef = useRef<number>(0)
  const progressCountRef = useRef<number>(0)
  const completionNarratingRef = useRef<boolean>(false)
  const playedExecutingRef = useRef<Set<string>>(new Set())

  // 触发进度播报的统一入口（带节流）
  const maybePlayProgress = async (
    milestone: 'thinking' | 'skill_selected' | 'skill_executing' | 'skill_complete',
    skill?: string,
  ) => {
    if (!autoPlayRef.current) return
    if (completionNarratingRef.current) return
    // 简单意图跳过
    const intentionType = useChatStore.getState().currentIntention?.intents?.[0]?.type
    if (intentionType && PROGRESS_SKIP_INTENTS.has(intentionType)) return
    // 长任务门控：未达到阈值不播
    if (taskStartRef.current && Date.now() - taskStartRef.current < LONG_TASK_THRESHOLD_MS) return
    // 节流：间隔 + 次数
    const now = Date.now()
    if (now - lastProgressTimeRef.current < PROGRESS_MIN_INTERVAL_MS) return
    if (progressCountRef.current >= PROGRESS_MAX_COUNT) return
    // skill_executing 同一 skill 只播一次
    if (milestone === 'skill_executing' && skill && playedExecutingRef.current.has(skill)) return

    const text = await narrateProgress({ milestone, skill })
    if (!text) return

    // 再次检查（narrateProgress 期间状态可能变化）
    if (completionNarratingRef.current) return
    if (!autoPlayRef.current) return

    lastProgressTimeRef.current = now
    progressCountRef.current += 1
    if (milestone === 'skill_executing' && skill) playedExecutingRef.current.add(skill)
    // 用临时 ID 播放，避免和完成播报冲突
    play(`progress-${Date.now()}`, text, {})
  }

  const scrollToBottom = (smooth = true) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    setAtBottom(true)
    setShowJump(false)
  }

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    setAtBottom(near)
    if (near) setShowJump(false)
  }

  useEffect(() => {
    if (messages.length === 0) return

    if (isProcessing) {
      if (atBottom) scrollToBottom(false)
      else setShowJump(true)
      return
    }

    const last = messages[messages.length - 1]
    if (last?.role === 'assistant' && atBottom) {
      const container = scrollRef.current
      const nodes = container?.querySelectorAll<HTMLElement>('[data-message-role="user"]')
      const el = nodes?.[nodes.length - 1]
      if (container && el) {
        const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
        container.scrollTo({ top: Math.max(0, top - 8), behavior: 'auto' })
        return
      }
    }

    if (atBottom) scrollToBottom(false)
    else setShowJump(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, isProcessing])

  const handleSend = async (text: string) => {
    const store = useChatStore.getState()

    if (store.isProcessing) return

    // 关键：先中断上一轮可能仍在途的流。
    // 行程规划类请求要跑 20~45 秒，用户此时点「清空对话」或刷新后继续提问，
    // 旧流若不掐断，它的回调会继续写「最后一条 AI 消息」，表现成已读乱回。
    abortActiveRequest()

    if (!store.sessionId) {
      const session = await createSession(store.userId)
      store.setSessionId(session.session_id)
    }

    const userMessageId = uid()
    // 本轮请求专属的 AI 消息 id，所有回调只认这个 id
    const assistantMessageId = uid()

    store.addMessage({
      id: userMessageId,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    })

    store.addMessage({
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      startedAt: Date.now(),
    })
    activeAssistantIdRef.current = assistantMessageId

    store.setProcessing(true)
    store.setCurrentIntention(null)
    requestAnimationFrame(() => scrollToBottom(false))
    store.resetAgentResults()
    store.clearRunningAgents()

    // 重置进度播报状态
    taskStartRef.current = Date.now()
    lastProgressTimeRef.current = 0
    progressCountRef.current = 0
    completionNarratingRef.current = false
    playedExecutingRef.current = new Set()

    try {
      await sendChatMessage(store.userId, text, store.sessionId, {
        onThinking: (data) => {
          store.setThinkingStatus(data.status)
        },
        onIntention: (data) => {
          store.setCurrentIntention(data)
          store.patchMessage(assistantMessageId, { intention: data })
          // 意图确定 → skill_selected 进度播报
          void maybePlayProgress('skill_selected')
        },
        onDispatching: () => {
          store.setThinkingStatus('dispatching')
        },
        onAgentStart: (data) => {
          store.addRunningAgent(data.agent_name)
          // 子 agent 开始 → skill_executing 进度播报
          void maybePlayProgress('skill_executing', data.agent_name)
        },
        onAgentResult: (data) => {
          store.addAgentResult(data)
          store.appendAgentResultById(assistantMessageId, data)
          store.removeRunningAgent(data.agent_name)
          // 子 agent 完成 → skill_complete 进度播报（仅 success）
          if (data.status === 'success') {
            void maybePlayProgress('skill_complete', data.agent_name)
          }
        },
        onComplete: async (data: OrchestrationResult) => {
          store.setOrchestrationResult(data)
          store.patchMessage(assistantMessageId, {
            agentResults: data.results,
            orchestrationResult: data,
          })
          const fallbackText = extractTTSTexts(data.results)
          if (fallbackText) {
            store.patchMessage(assistantMessageId, { content: fallbackText })
          }
          // 费用记录成功后通知侧边栏刷新
          for (const r of data.results) {
            if (r.agent_name === 'expense_tracking' && r.status === 'success') {
              window.dispatchEvent(new CustomEvent('expense-updated'))
            }
            if (r.agent_name === 'preference' && r.status === 'success') {
              window.dispatchEvent(new CustomEvent('preference-updated'))
            }
          }
          // 自动朗读
          if (!autoPlayRef.current || !fallbackText) return

          const intentionType = data.intention?.intents?.[0]?.type
          // 用本轮请求自己的消息 id，不再按「最后一条 assistant」猜
          const assistantMsgId = assistantMessageId

          // 标记完成播报进行中（阻止进度播报抢占）
          completionNarratingRef.current = true

          // 简单意图走快路径（不调 LLM）；复杂意图调 narrate，失败回退 fallbackText
          let textToPlay = fallbackText
          if (!FAST_PATH_INTENTS.has(intentionType || '')) {
            const narrated = await narrate({
              intention: intentionType,
              resultData: data.results,
            })
            if (narrated) {
              textToPlay = narrated
              // 存到 message，手动播放按钮可复用
              store.patchMessage(assistantMessageId, { narrationText: narrated })
            }
          }
          play(assistantMsgId, textToPlay, { intention: intentionType })
        },
        onClarification: (data) => {
          store.patchMessage(assistantMessageId, { content: data.question })
          store.setThinkingStatus('')
        },
        onError: (data) => {
          store.patchMessage(assistantMessageId, { content: `❌ ${data.message}` })
        },
      })
    } catch (err) {
      store.patchMessage(assistantMessageId, {
        content: `❌ 连接失败: ${err instanceof Error ? err.message : String(err)}`,
      })
    } finally {
      store.setProcessing(false)
      store.setThinkingStatus('')
    }
  }

  useEffect(() => {
    const onOnline = () => setOffline(false)
    const onOffline = () => setOffline(true)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  const handleCancel = () => {
    abortActiveRequest()
    const store = useChatStore.getState()
    store.setProcessing(false)
    store.setThinkingStatus('')
    store.updateLastAssistant({ content: '⏹ 已停止生成' })
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto py-2">
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center px-4 py-10">
              <div className="w-full max-w-[760px]">
                <div className="font-mono text-[10px] tracking-[0.18em] text-accent">ALIGO / 行程文件</div>
                <h1 className="mt-3 font-display text-[30px] leading-[1.18] text-ink md:text-[38px]">
                  把行程，
                  <br />
                  做成一份文件。
                </h1>
                <p className="mt-3 max-w-[460px] text-sm leading-7 text-ink-2">
                  告诉我出差的时间、地点和预算，我会排好行程、查差旅政策、记住你的偏好。
                </p>

                <div className="mt-7 border-t border-rule">
                  {[
                    { n: '01', title: '明天北京 → 上海，3 天，预算 2000', meta: '行程规划', q: '明天从北京去上海出差3天，预算2000' },
                    { n: '02', title: '上海住宿标准是多少？', meta: '差旅政策', q: '上海住宿标准是多少？' },
                    { n: '03', title: '记一笔打车费 50 元', meta: '费用记录', q: '记一笔打车费50元' },
                  ].map((item) => (
                    <button
                      key={item.n}
                      type="button"
                      onClick={() => handleSend(item.q)}
                      className="group flex w-full items-baseline gap-3 border-b border-rule py-3 text-left hover:bg-paper-sunken"
                    >
                      <span className="font-mono text-[10px] text-accent">{item.n}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-ink">{item.title}</span>
                        <span className="mt-0.5 block text-[11px] text-ink-3">{item.meta}</span>
                      </span>
                      <ArrowUpRight
                        size={14}
                        className="text-ink-3 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </button>
                  ))}
                </div>

                <div className="mt-5 flex flex-wrap gap-2">
                  {['北京天气怎么样？', '100 美元多少人民币', '我住酒店喜欢汉庭', '查询差旅记录'].map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => handleSend(q)}
                      className="rounded-[2px] border border-rule-strong px-2.5 py-1.5 text-[11px] text-ink-2 hover:bg-paper-sunken hover:text-ink"
                    >
                      {q}
                    </button>
                  ))}
                </div>

                <div className="mt-6 font-mono text-[10px] tracking-[0.04em] text-ink-3">
                  ENTER 发送 · SHIFT+ENTER 换行
                </div>
              </div>
            </div>
          )}

          {messages.map((msg, i) => {
            const isLastAssistant =
              msg.role === 'assistant' &&
              i === messages.length - 1 &&
              isProcessing
            let userMessage = ''
            if (msg.role === 'assistant') {
              for (let j = i - 1; j >= 0; j--) {
                if (messages[j].role === 'user') {
                  userMessage = messages[j].content
                  break
                }
              }
            }
            return (
              <MessageBubble
                key={msg.id}
                msg={msg}
                isRunning={isLastAssistant}
                isLatest={i === messages.length - 1 && !isProcessing}
                onSend={handleSend}
                userMessage={userMessage}
              />
            )
          })}

          {isProcessing && (
            <div className="px-4 pb-2 md:px-6">
              <div className="mx-auto max-w-[760px]">
                <RouteStrip
                  intention={currentIntention}
                  results={currentAgents}
                  running={runningAgents}
                  onCancel={handleCancel}
                />
              </div>
            </div>
          )}
        </div>

        {showJump && (
          <button
            type="button"
            onClick={() => scrollToBottom(true)}
            className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-[2px] border border-rule-strong bg-paper-raised px-3 py-1.5 text-[11px] text-ink shadow-sm hover:bg-paper-sunken"
          >
            新消息 ↓
          </button>
        )}
      </div>

      {offline && (
        <div className="border-t border-warn/30 bg-warning-light px-4 py-2 text-[11px] text-warn">
          当前处于离线状态，恢复网络后再发送。
        </div>
      )}

      <InputBar onSend={handleSend} onCancel={handleCancel} disabled={isProcessing} />
    </div>
  )
}
