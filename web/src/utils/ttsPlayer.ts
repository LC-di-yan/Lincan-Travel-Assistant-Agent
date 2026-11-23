const SAMPLE_RATE = 24000
const PREBUFFER_CHUNKS = 2
export type TTSStatus = 'idle' | 'loading' | 'playing'

export class TTSPlayer {
  private audioContext: AudioContext | null = null
  private nextPlayTime = 0
  private abortController: AbortController | null = null
  private sourceNodes: AudioBufferSourceNode[] = []
  private generation = 0
  private onStop: (() => void) | null = null

  private ensureContext(): AudioContext {
    if (!this.audioContext) {
      const browser = window as Window & { webkitAudioContext?: typeof AudioContext }
      const Constructor = window.AudioContext || browser.webkitAudioContext
      if (!Constructor) throw new Error('当前浏览器不支持语音播放')
      this.audioContext = new Constructor({ sampleRate: SAMPLE_RATE })
    }
    return this.audioContext
  }

  async play(text: string, options: { personaId?: string; intention?: string; onStatus?: (status: TTSStatus) => void } = {}): Promise<void> {
    this.stop()
    const generation = this.generation
    const controller = new AbortController()
    this.abortController = controller
    const current = () => this.generation === generation && !controller.signal.aborted
    const emit = (status: TTSStatus) => { if (current()) options.onStatus?.(status) }
    this.onStop = () => options.onStatus?.('idle')
    emit('loading')

    let context: AudioContext
    try {
      context = this.ensureContext()
      if (context.state === 'suspended') await context.resume()
    } catch (error) {
      console.error('[语音播放] 初始化失败', error)
      emit('idle')
      return
    }
    if (!current()) return
    this.nextPlayTime = context.currentTime

    let response: Response
    try {
      response = await fetch('/api/tts', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, persona_id: options.personaId, intention: options.intention }),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`语音服务返回 ${response.status}`)
    } catch (error) {
      if (current()) { console.error('[语音播放] 请求失败', error); emit('idle') }
      return
    }
    const reader = response.body?.getReader()
    if (!reader) { emit('idle'); return }
    const decoder = new TextDecoder()
    let buffer = '', pendingByte: number | null = null
    const queue: AudioBuffer[] = []
    let started = false, streamEnded = false
    const finish = () => {
      if (current() && streamEnded && this.sourceNodes.length === 0 && queue.length === 0) {
        emit('idle')
        this.onStop = null
        this.abortController = null
      }
    }
    const schedule = (force = false) => {
      if (!current()) return
      if (!started && queue.length > 0 && (force || queue.length >= PREBUFFER_CHUNKS)) {
        started = true
        emit('playing')
      }
      while (started && queue.length) {
        const audio = queue.shift()!
        const source = context.createBufferSource()
        source.buffer = audio
        source.connect(context.destination)
        const startAt = Math.max(this.nextPlayTime, context.currentTime)
        this.sourceNodes.push(source)
        source.onended = () => {
          const index = this.sourceNodes.indexOf(source)
          if (index >= 0) this.sourceNodes.splice(index, 1)
          finish()
        }
        source.start(startAt)
        this.nextPlayTime = startAt + audio.duration
      }
    }
    const consume = (line: string) => {
      if (!line.startsWith('data:')) return
      let data: { chunk?: string; message?: string }
      try { data = JSON.parse(line.slice(5).trim()) } catch { return }
      if (data.message) { console.error('[语音播放] 服务错误', data.message); return }
      if (!data.chunk) return
      const binary = atob(data.chunk)
      const bytes = pendingByte === null ? [] : [pendingByte]
      for (let i = 0; i < binary.length; i++) bytes.push(binary.charCodeAt(i))
      pendingByte = bytes.length % 2 ? bytes.pop()! : null
      if (!bytes.length) return
      const samples = new Float32Array(bytes.length / 2)
      for (let i = 0; i < samples.length; i++) {
        const sample = (bytes[i * 2 + 1] << 8) | bytes[i * 2]
        samples[i] = (sample > 0x7fff ? sample - 0x10000 : sample) / 32768
      }
      const audio = context.createBuffer(1, samples.length, SAMPLE_RATE)
      audio.copyToChannel(samples, 0)
      queue.push(audio)
      schedule()
    }
    try {
      while (current()) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) if (current()) consume(line)
      }
      buffer += decoder.decode()
      if (buffer.trim() && current()) consume(buffer)
    } catch (error) {
      if (current()) console.error('[语音播放] 连接中断', error)
    } finally {
      reader.releaseLock()
      streamEnded = true
      // 结束时强制排出不足两块的音频；完成状态由音源结束事件驱动，无轮询定时器。
      if (current()) { schedule(true); finish() }
      else queue.length = 0
    }
  }

  stop() {
    this.generation++
    this.abortController?.abort()
    this.abortController = null
    this.onStop?.()
    this.onStop = null
    for (const source of this.sourceNodes) {
      try { source.stop() } catch { /* 音源可能已结束 */ }
    }
    this.sourceNodes = []
    if (this.audioContext) this.nextPlayTime = this.audioContext.currentTime
  }
}
