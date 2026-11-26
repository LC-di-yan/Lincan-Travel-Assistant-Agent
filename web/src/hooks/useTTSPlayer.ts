import { useRef, useCallback, useState } from 'react'
import { useTTSPrefsStore } from './useTTSPrefs'

import { TTSPlayer, type TTSStatus } from '../utils/ttsPlayer'
export type { TTSStatus } from '../utils/ttsPlayer'

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
    if (currentMessageIdRef.current === messageId) {
      playerInstance?.stop()
      return
    }

    // The singleton cancels the previous stream before starting the next one.
    currentMessageIdRef.current = messageId
    setActiveMessageId(messageId)
    const pid = options.personaId || personaId
    await getPlayer().play(text, {
      personaId: pid,
      intention: options.intention,
      onStatus: (s) => {
        if (currentMessageIdRef.current !== messageId) return
        setStatus(s)
        if (s === 'idle') {
          if (currentMessageIdRef.current === messageId) {
            setActiveMessageId(null)
            currentMessageIdRef.current = null
          }
        }
      },
    })
  }, [personaId])

  const stop = useCallback(() => {
    getPlayer().stop()
    setStatus('idle')
    setActiveMessageId(null)
    currentMessageIdRef.current = null
  }, [])

  const stopOwned = useCallback(() => {
    if (currentMessageIdRef.current !== null) playerInstance?.stop()
  }, [])

  return { status, activeMessageId, play, stop, stopOwned }
}
