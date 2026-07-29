import { useRef, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { sendChatMessage, createSession, abortActiveRequest } from '../../api/client'
import { uid } from '../../store/chatStore'
import { MessageBubble } from './MessageBubble'
import { ThinkingIndicator } from './ThinkingIndicator'
import { InputBar } from './InputBar'
import type { OrchestrationResult } from '../../api/types'

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages)
  const isProcessing = useChatStore((s) => s.isProcessing)
  const thinkingStatus = useChatStore((s) => s.thinkingStatus)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isProcessing])

  const handleSend = async (text: string) => {
    const store = useChatStore.getState()

    if (!store.sessionId) {
      const session = await createSession(store.userId)
      store.setSessionId(session.session_id)
    }

    store.addMessage({
      id: uid(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    })

    store.addMessage({
      id: uid(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      startedAt: Date.now(),
    })

    store.setProcessing(true)
    store.setCurrentIntention(null)
    store.resetAgentResults()
    store.clearRunningAgents()

    try {
      await sendChatMessage(store.userId, text, store.sessionId, {
        onThinking: (data) => {
          store.setThinkingStatus(data.status)
        },
        onIntention: (data) => {
          store.setCurrentIntention(data)
          store.updateLastAssistant({ intention: data })
        },
        onDispatching: () => {
          store.setThinkingStatus('dispatching')
        },
        onAgentStart: (data) => {
          store.addRunningAgent(data.agent_name)
        },
        onAgentResult: (data) => {
          store.addAgentResult(data)
          store.appendAgentResultToMessage(data)
          store.removeRunningAgent(data.agent_name)
        },
        onComplete: (data: OrchestrationResult) => {
          store.setOrchestrationResult(data)
          store.updateLastAssistant({
            agentResults: data.results,
            orchestrationResult: data,
          })
          const textParts: string[] = []
          for (const r of data.results) {
            if (r.status === 'error') {
              const errDetail = (r.data as any)?.error || (r.data as any)?.message || ''
              textParts.push(errDetail ? `❌ ${r.agent_name}: ${errDetail}` : `❌ ${r.agent_name}: 执行失败`)
              continue
            }
            const d = r.data as Record<string, unknown>
            const answer = d.answer || d.content || d.result || d.message || d.summary || d.text || d.description
            if (answer && typeof answer === 'string') {
              textParts.push(answer)
            } else if (d.data && typeof d.data === 'object') {
              const inner = d.data as Record<string, unknown>
              const innerAnswer = inner.answer || inner.content || inner.result
              if (innerAnswer && typeof innerAnswer === 'string') {
                textParts.push(innerAnswer)
              }
            }
            // 费用记录成功后通知侧边栏刷新
            if (r.agent_name === 'expense_tracking' && r.status === 'success') {
              window.dispatchEvent(new CustomEvent('expense-updated'))
            }
            // 偏好更新成功后通知侧边栏刷新
            if (r.agent_name === 'preference' && r.status === 'success') {
              window.dispatchEvent(new CustomEvent('preference-updated'))
            }
          }
          if (textParts.length > 0) {
            store.updateLastAssistant({ content: textParts.join('\n\n') })
          }
        },
        onError: (data) => {
          store.updateLastAssistant({ content: `❌ ${data.message}` })
        },
      })
    } catch (err) {
      store.updateLastAssistant({
        content: `❌ 连接失败: ${err instanceof Error ? err.message : String(err)}`,
      })
    } finally {
      store.setProcessing(false)
      store.setThinkingStatus('')
    }
  }

  const handleCancel = () => {
    abortActiveRequest()
    const store = useChatStore.getState()
    store.setProcessing(false)
    store.setThinkingStatus('')
    store.updateLastAssistant({ content: '⏹ 已停止生成' })
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto py-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)] px-4">
            {/* Hero Illustration */}
            <div className="relative mb-6 animate-fade-in-up">
              <img
                src="/images/illustrations/welcome-hero.svg"
                alt="Travel"
                className="w-56 md:w-80 h-auto opacity-90"
                style={{ filter: 'drop-shadow(0 4px 24px rgba(79,142,247,0.12))' }}
              />
            </div>

            <p className="text-2xl font-bold text-gradient mb-2 animate-fade-in-up" style={{ animationDelay: '0.1s' }}>
              Aligo 智能旅行助手
            </p>
            <p className="text-sm text-[var(--text-muted)] max-w-md text-center leading-relaxed mb-8 animate-fade-in-up" style={{ animationDelay: '0.15s' }}>
              告诉我您的差旅需求，我会为您规划行程、查询信息、管理偏好
            </p>

            {/* Feature cards */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 md:gap-3 max-w-lg mb-6 animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
              {[
                { icon: '/images/icons/agent-itinerary.svg', title: '行程规划', desc: '智能安排出差行程', color: '#4f8ef7', q: '明天从北京去上海出差3天' },
                { icon: '/images/icons/agent-rag.svg', title: '知识查询', desc: '差旅政策一键查', color: '#8b5cf6', q: '出差住宿标准是多少？' },
                { icon: '/images/icons/agent-pref.svg', title: '偏好管理', desc: '记住您的喜好', color: '#ec4899', q: '我住酒店喜欢汉庭' },
              ].map((card) => (
                <button
                  key={card.title}
                  onClick={() => handleSend(card.q)}
                  className="flex flex-col items-center gap-2.5 p-4 rounded-2xl transition-all card-hover text-center group"
                  style={{
                    border: '1px solid var(--border)',
                    backgroundColor: 'var(--bg-elevated)',
                    boxShadow: 'var(--shadow-sm)',
                  }}
                >
                  <img src={card.icon} alt={card.title} width={32} height={32}
                    className="transition-transform duration-300 group-hover:scale-110" />
                  <div>
                    <p className="text-sm font-semibold" style={{ color: card.color }}>{card.title}</p>
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">{card.desc}</p>
                  </div>
                </button>
              ))}
            </div>

            {/* Quick input suggestions */}
            <div className="flex flex-wrap justify-center gap-2 max-w-xl animate-fade-in-up" style={{ animationDelay: '0.25s' }}>
              {[
                { label: '北京天气怎么样？', icon: '🌤️' },
                { label: '查询差旅记录', icon: '📋' },
                { label: '100美元多少人民币', icon: '💱' },
                { label: '记一笔打车费50元', icon: '🚕' },
              ].map((q) => (
                <button
                  key={q.label}
                  onClick={() => handleSend(q.label)}
                  className="text-xs px-4 py-2 rounded-full transition-all hover:scale-105 active:scale-95"
                  style={{
                    border: '1px solid var(--border)',
                    backgroundColor: 'var(--bg-elevated)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  <span className="mr-1">{q.icon}</span> {q.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => {
          const isLastAssistant =
            msg.role === 'assistant' &&
            i === messages.length - 1 &&
            isProcessing
          return <MessageBubble key={msg.id} msg={msg} isRunning={isLastAssistant} />
        })}

        {isProcessing && <ThinkingIndicator status={thinkingStatus} />}

        <div ref={bottomRef} />
      </div>

      <InputBar onSend={handleSend} onCancel={handleCancel} disabled={isProcessing} />
    </div>
  )
}
