import { useState, useCallback } from 'react'
import { useTTSPrefsStore } from './useTTSPrefs'

export interface NarrateRequest {
  intention?: string
  resultData?: unknown
  personaId?: string
}

export interface NarrateProgressRequest {
  milestone: 'thinking' | 'skill_selected' | 'skill_executing' | 'skill_complete'
  skill?: string
  context?: Record<string, unknown>
  personaId?: string
}

export interface NarrateResult {
  text: string  // 完整播报文案
  fromCache?: boolean  // 是否来自缓存
}

/**
 * 调 /api/narrate 流式生成播报文案。
 * - 失败时返回 null，让调用方走 extractTTSText 兜底
 * - 简单意图不走 LLM（在 ChatPanel 里判断）
 */
export function useNarrate() {
  const [isNarrating, setIsNarrating] = useState(false)
  const personaId = useTTSPrefsStore((s) => s.personaId)

  const narrate = useCallback(async (req: NarrateRequest): Promise<string | null> => {
    const pid = req.personaId || personaId
    const body = JSON.stringify({
      intention: req.intention,
      result_data: req.resultData,
      persona_id: pid,
    })

    let resp: Response
    try {
      resp = await fetch('/api/narrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      })
    } catch (err) {
      console.error('[Narrate] fetch failed:', err)
      return null
    }

    if (!resp.ok) {
      console.error(`[Narrate] HTTP ${resp.status}`)
      return null
    }

    const reader = resp.body?.getReader()
    if (!reader) return null

    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = ''
    let fullText = ''
    let hadError = false

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const dataStr = line.slice(5).trim()
            if (!dataStr) continue
            try {
              const data = JSON.parse(dataStr)
              if (currentEvent === 'delta' && data.text) {
                fullText += data.text
              } else if (currentEvent === 'error') {
                console.error('[Narrate] server error:', data.message)
                hadError = true
              }
              // done 事件：流结束，正常退出
            } catch {
              // ignore parse errors
            }
            currentEvent = ''  // data 行处理后清空 event
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    if (hadError || !fullText.trim()) return null
    return fullText.trim()
  }, [personaId])

  /**
   * 进度播报：调 /api/narrate/progress，返回短文案。
   * 模板优先（0 延迟），LLM 兜底。
   * 失败返回 null。
   */
  const narrateProgress = useCallback(async (req: NarrateProgressRequest): Promise<string | null> => {
    const pid = req.personaId || personaId
    try {
      const resp = await fetch('/api/narrate/progress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          milestone: req.milestone,
          skill: req.skill,
          context: req.context,
          persona_id: pid,
        }),
      })
      if (!resp.ok) return null
      const data = await resp.json()
      const text = (data?.text as string) || ''
      return text.trim() || null
    } catch (err) {
      console.error('[Narrate/Progress] failed:', err)
      return null
    }
  }, [personaId])

  return { narrate, narrateProgress, isNarrating, setIsNarrating }
}

