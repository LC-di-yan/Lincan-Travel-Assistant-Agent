import { useState, useEffect, useRef, useCallback } from 'react'

interface UseSpeechRecognitionOptions {
  lang?: string
  continuous?: boolean
  interimResults?: boolean
  onFinal?: (text: string) => void
  onIssue?: (message: string) => void
}

interface UseSpeechRecognitionReturn {
  isListening: boolean
  isSupported: boolean
  interimText: string
  finalText: string
  startListening: () => void
  stopListening: () => void
  reset: () => void
}

interface SpeechResultEvent {
  resultIndex: number
  results: ArrayLike<{ isFinal: boolean; [index: number]: { transcript: string } }>
}
interface BrowserRecognition {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechResultEvent) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}
type RecognitionConstructor = new () => BrowserRecognition
type SpeechWindow = Window & { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor }

export function useSpeechRecognition({
  lang = 'zh-CN',
  continuous = false,
  interimResults = true,
  onFinal, onIssue,
}: UseSpeechRecognitionOptions = {}): UseSpeechRecognitionReturn {
  const [isListening, setIsListening] = useState(false)
  const [interimText, setInterimText] = useState('')
  const [finalText, setFinalText] = useState('')
  const recognitionRef = useRef<BrowserRecognition | null>(null)
  const onFinalRef = useRef(onFinal)
  const onIssueRef = useRef(onIssue)
  const autoStopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const constructor = typeof window === 'undefined' ? undefined :
    ((window as SpeechWindow).SpeechRecognition || (window as SpeechWindow).webkitSpeechRecognition)
  const isSupported = Boolean(constructor)

  useEffect(() => {
    onFinalRef.current = onFinal
    onIssueRef.current = onIssue
  }, [onFinal, onIssue])

  useEffect(() => {
    if (!constructor) return
    const recognition = new constructor()
    recognition.lang = lang
    recognition.continuous = continuous
    recognition.interimResults = interimResults

    recognition.onresult = (event: SpeechResultEvent) => {
      let interim = ''
      let final = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          final += transcript
        } else {
          interim += transcript
        }
      }
      if (interim) setInterimText(interim)
      if (final) {
        setFinalText((prev) => prev + final)
        setInterimText('')
        if (onFinalRef.current) onFinalRef.current(final)
      }
    }

    recognition.onerror = (event: { error: string }) => {
      if (autoStopTimerRef.current) { clearTimeout(autoStopTimerRef.current); autoStopTimerRef.current = null }
      if (event.error !== 'aborted') onIssueRef.current?.(
        event.error === 'not-allowed' || event.error === 'service-not-allowed' ? '未获得麦克风权限。可以继续打字，或在浏览器设置中允许麦克风。' :
        event.error === 'no-speech' ? '未听到语音。请再试一次，或直接输入文字。' : '语音输入暂不可用。可以继续打字。',
      )
      setIsListening(false)
      setInterimText('')
    }

    recognition.onend = () => {
      setIsListening(false)
      setInterimText('')
      if (autoStopTimerRef.current) {
        clearTimeout(autoStopTimerRef.current)
        autoStopTimerRef.current = null
      }
    }

    recognitionRef.current = recognition

    return () => {
      recognition.onresult = null; recognition.onend = null; recognition.onerror = null
      recognitionRef.current = null
      try {
        recognition.stop()
      } catch { /* noop */ }
      if (autoStopTimerRef.current) {
        clearTimeout(autoStopTimerRef.current)
        autoStopTimerRef.current = null
      }
    }
  }, [constructor, lang, continuous, interimResults])

  const startListening = useCallback(() => {
    if (!recognitionRef.current || isListening) return
    setFinalText('')
    setInterimText('')
    try {
      recognitionRef.current.start()
      setIsListening(true)
      // 安全超时：15s 无 final 结果自动停止，避免无限收音
      autoStopTimerRef.current = setTimeout(() => {
        try { recognitionRef.current?.stop() } catch { /* noop */ }
      }, 15000)
    } catch {
      onIssueRef.current?.('无法启动麦克风。请检查浏览器权限，或直接输入文字。')
    }
  }, [isListening])

  const stopListening = useCallback(() => {
    if (!recognitionRef.current) return
    try {
      recognitionRef.current.stop()
    } catch { /* noop */ }
    setIsListening(false)
    if (autoStopTimerRef.current) {
      clearTimeout(autoStopTimerRef.current)
      autoStopTimerRef.current = null
    }
  }, [])

  const reset = useCallback(() => {
    setFinalText('')
    setInterimText('')
  }, [])

  return {
    isListening,
    isSupported,
    interimText,
    finalText,
    startListening,
    stopListening,
    reset,
  }
}
