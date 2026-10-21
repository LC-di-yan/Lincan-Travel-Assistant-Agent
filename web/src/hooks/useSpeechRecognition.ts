import { useState, useEffect, useRef, useCallback } from 'react'

interface UseSpeechRecognitionOptions {
  lang?: string
  continuous?: boolean
  interimResults?: boolean
  onFinal?: (text: string) => void
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

export function useSpeechRecognition({
  lang = 'zh-CN',
  continuous = false,
  interimResults = true,
  onFinal,
}: UseSpeechRecognitionOptions = {}): UseSpeechRecognitionReturn {
  const [isListening, setIsListening] = useState(false)
  const [interimText, setInterimText] = useState('')
  const [finalText, setFinalText] = useState('')
  const recognitionRef = useRef<any>(null)
  const onFinalRef = useRef(onFinal)
  const autoStopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const isSupported = typeof window !== 'undefined' &&
    !!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition

  useEffect(() => {
    onFinalRef.current = onFinal
  }, [onFinal])

  useEffect(() => {
    if (!isSupported) return

    const SRCtor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    const recognition = new SRCtor()
    recognition.lang = lang
    recognition.continuous = continuous
    recognition.interimResults = interimResults

    recognition.onresult = (event: any) => {
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

    recognition.onerror = (event: any) => {
      console.warn('[SpeechRecognition] error:', event.error)
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
      try {
        recognition.stop()
      } catch { /* noop */ }
      if (autoStopTimerRef.current) {
        clearTimeout(autoStopTimerRef.current)
        autoStopTimerRef.current = null
      }
    }
  }, [isSupported, lang, continuous, interimResults])

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
    } catch (e) {
      console.warn('[SpeechRecognition] start failed:', e)
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
