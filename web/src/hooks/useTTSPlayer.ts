import { useRef, useCallback, useState } from 'react'
import { useTTSPrefsStore } from './useTTSPrefs'

const SAMPLE_RATE = 24000  // MiMo PCM16 固定 24kHz
const PREBUFFER_CHUNKS = 2  // 预缓冲 2 个 chunk 再开播

export type TTSStatus = 'idle' | 'loading' | 'playing'

class TTSPlayer {
  private audioContext: AudioContext | null = null
  private nextPlayTime: number = 0
  private abortController: AbortController | null = null
  private sourceNodes: AudioBufferSourceNode[] = []

  private ensureContext(): AudioContext {
    if (!this.audioContext) {
      const Ctor = (window as any).AudioContext || (window as any).webkitAudioContext
      this.audioContext = new Ctor({ sampleRate: SAMPLE_RATE })
    }
    return this.audioContext!
  }

  async play(
    text: string,
    options: { personaId?: string; intention?: string; onStatus?: (s: TTSStatus) => void } = {},
  ): Promise<void> {
    // 停止上一次播放
    this.stop()

    const ctx = this.ensureContext()
    if (ctx.state === 'suspended') {
      try { await ctx.resume() } catch { /* noop */ }
    }

    this.nextPlayTime = ctx.currentTime
    this.abortController = new AbortController()
    options.onStatus?.('loading')

    const body = JSON.stringify({
      text,
      persona_id: options.personaId,
      intention: options.intention,
    })

    let resp: Response
    try {
      resp = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        signal: this.abortController.signal,
      })
    } catch (err) {
      if (this.abortController.signal.aborted) return
      console.error('[TTS] fetch failed:', err)
      options.onStatus?.('idle')
      return
    }

    if (!resp.ok) {
      console.error(`[TTS] HTTP ${resp.status}`)
      options.onStatus?.('idle')
      return
    }

    const reader = resp.body?.getReader()
    if (!reader) {
      options.onStatus?.('idle')
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let pendingBytes: number[] = []  // 跨 chunk 的奇数字节缓冲
    const chunkQueue: AudioBuffer[] = []
    let started = false

    const scheduleQueue = () => {
      if (!started && chunkQueue.length >= PREBUFFER_CHUNKS) {
        started = true
        options.onStatus?.('playing')
      }
      while (started && chunkQueue.length > 0) {
        const buf = chunkQueue.shift()!
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.connect(ctx.destination)
        const startAt = Math.max(this.nextPlayTime, ctx.currentTime)
        src.start(startAt)
        this.nextPlayTime = startAt + buf.duration
        this.sourceNodes.push(src)
        src.onended = () => {
          const i = this.sourceNodes.indexOf(src)
          if (i >= 0) this.sourceNodes.splice(i, 1)
        }
      }
    }

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event:')) continue
          if (!line.startsWith('data:')) continue
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            if (data.chunk) {
              // base64 → 字节数组
              const binStr = atob(data.chunk)
              const all = [...pendingBytes]
              for (let i = 0; i < binStr.length; i++) {
                all.push(binStr.charCodeAt(i))
              }
              // 处理奇数字节边界
              pendingBytes = all.length % 2 !== 0 ? [all.pop()!] : []

              if (all.length < 2) continue

              // Int16 → Float32（归一化到 [-1, 1]）
              const sampleCount = all.length / 2
              const float32 = new Float32Array(sampleCount)
              for (let i = 0; i < sampleCount; i++) {
                const lo = all[i * 2]
                const hi = all[i * 2 + 1]
                // 小端序
                const int16 = (hi << 8) | lo
                const signed = int16 > 0x7fff ? int16 - 0x10000 : int16
                float32[i] = signed / 32768
              }

              const audioBuf = ctx.createBuffer(1, float32.length, SAMPLE_RATE)
              audioBuf.copyToChannel(float32, 0)
              chunkQueue.push(audioBuf)
              scheduleQueue()
            } else if (data.message) {
              // error 事件
              console.error('[TTS] server error:', data.message)
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } finally {
      reader.releaseLock()
      // 如果还有未播完的 chunk，让它们继续播完；状态在所有 source onended 后转 idle
      const checkComplete = () => {
        if (this.sourceNodes.length === 0 && chunkQueue.length === 0) {
          options.onStatus?.('idle')
        } else {
          setTimeout(checkComplete, 100)
        }
      }
      // 兜底：3 秒后强制 idle（防止 onended 不触发）
      setTimeout(() => options.onStatus?.('idle'), 3000)
      checkComplete()
    }
  }

  stop() {
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }
    for (const src of this.sourceNodes) {
      try { src.stop() } catch { /* noop */ }
    }
    this.sourceNodes = []
    if (this.audioContext) {
      this.nextPlayTime = this.audioContext.currentTime
    }
  }
}

// 单例播放器（同一时间只播一条消息）
let playerInstance: TTSPlayer | null = null
function getPlayer(): TTSPlayer {
  if (!playerInstance) playerInstance = new TTSPlayer()
  return playerInstance
}

export function useTTSPlayer() {
  const [status, setStatus] = useState<TTSStatus>('idle')
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null)
  const currentMessageIdRef = useRef<string | null>(null)
  const personaId = useTTSPrefsStore((s) => s.personaId)

  const play = useCallback(async (
    messageId: string,
    text: string,
    options: { personaId?: string; intention?: string } = {},
  ) => {
    // 同一条消息再点一次 → 停止
    if (status === 'playing' && activeMessageId === messageId) {
      getPlayer().stop()
      setStatus('idle')
      setActiveMessageId(null)
      currentMessageIdRef.current = null
      return
    }

    // 切换到新消息 → 先停旧的
    if (status !== 'idle') {
      getPlayer().stop()
    }

    currentMessageIdRef.current = messageId
    setActiveMessageId(messageId)
    const pid = options.personaId || personaId
    await getPlayer().play(text, {
      personaId: pid,
      intention: options.intention,
      onStatus: (s) => {
        setStatus(s)
        if (s === 'idle') {
          if (currentMessageIdRef.current === messageId) {
            setActiveMessageId(null)
            currentMessageIdRef.current = null
          }
        }
      },
    })
  }, [status, activeMessageId, personaId])

  const stop = useCallback(() => {
    getPlayer().stop()
    setStatus('idle')
    setActiveMessageId(null)
    currentMessageIdRef.current = null
  }, [])

  return { status, activeMessageId, play, stop }
}
