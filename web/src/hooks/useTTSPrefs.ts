import { create } from 'zustand'
import { useEffect } from 'react'

export interface TTSPrefs {
  personaId: string  // 默认 loli_guide
  autoPlay: boolean
}

// v3：强制 autoPlay 一次性重置为 false（此前版本可能被测试时误开）
// 用户手动开启后会重新写入 localStorage，后续保持
const STORAGE_KEY = 'aligo-tts-prefs-v3'
const LEGACY_KEYS = ['aligo-tts-prefs-v2', 'aligo-tts-prefs-v1']

function loadPrefs(): TTSPrefs {
  const defaults: TTSPrefs = { personaId: 'loli_guide', autoPlay: false }
  if (typeof window === 'undefined') return defaults
  try {
    // 清理旧版本 key（一次性）
    for (const k of LEGACY_KEYS) {
      if (localStorage.getItem(k)) localStorage.removeItem(k)
    }
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return defaults
    const parsed = JSON.parse(raw)
    return {
      personaId: typeof parsed.personaId === 'string' ? parsed.personaId : defaults.personaId,
      autoPlay: typeof parsed.autoPlay === 'boolean' ? parsed.autoPlay : defaults.autoPlay,
    }
  } catch {
    return defaults
  }
}

export interface PersonaMeta {
  id: string
  label: string
  voice: string
  lang: string
  emoji: string
  sample_text: string
}

interface TTSPrefsStore extends TTSPrefs {
  personas: PersonaMeta[]
  personasLoaded: boolean
  setPersonaId: (id: string) => void
  setAutoPlay: (v: boolean) => void
  setPersonas: (p: PersonaMeta[]) => void
}

export const useTTSPrefsStore = create<TTSPrefsStore>((set) => {
  const initial = loadPrefs()
  return {
    ...initial,
    personas: [],
    personasLoaded: false,
    setPersonaId: (personaId) => {
      set({ personaId })
      try {
        const raw = localStorage.getItem(STORAGE_KEY)
        const cur = raw ? JSON.parse(raw) : {}
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cur, personaId }))
      } catch { /* noop */ }
    },
    setAutoPlay: (autoPlay) => {
      set({ autoPlay })
      try {
        const raw = localStorage.getItem(STORAGE_KEY)
        const cur = raw ? JSON.parse(raw) : {}
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cur, autoPlay }))
      } catch { /* noop */ }
    },
    setPersonas: (personas) => set({ personas, personasLoaded: true }),
  }
})

// 从后端拉取角色列表（仅一次）
export function useLoadPersonas() {
  const personasLoaded = useTTSPrefsStore((s) => s.personasLoaded)
  const setPersonas = useTTSPrefsStore((s) => s.setPersonas)
  useEffect(() => {
    if (personasLoaded) return
    fetch('/api/tts/personas')
      .then((r) => r.json())
      .then((data) => {
        if (data?.personas?.length) {
          setPersonas(data.personas)
          // 兜底：当前 personaId 不在列表里（如老用户存了已删除角色）→ 重置为第一个
          const store = useTTSPrefsStore.getState()
          if (!data.personas.some((p: PersonaMeta) => p.id === store.personaId)) {
            store.setPersonaId(data.personas[0].id)
          }
        }
      })
      .catch((e) => console.warn('[TTS] load personas failed:', e))
  }, [personasLoaded, setPersonas])
}

export function useTTSPrefs() {
  const personaId = useTTSPrefsStore((s) => s.personaId)
  const autoPlay = useTTSPrefsStore((s) => s.autoPlay)
  const personas = useTTSPrefsStore((s) => s.personas)
  const setPersonaId = useTTSPrefsStore((s) => s.setPersonaId)
  const setAutoPlay = useTTSPrefsStore((s) => s.setAutoPlay)

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY || !e.newValue) return
      try {
        const parsed = JSON.parse(e.newValue)
        if (typeof parsed.personaId === 'string') useTTSPrefsStore.setState({ personaId: parsed.personaId })
        if (typeof parsed.autoPlay === 'boolean') useTTSPrefsStore.setState({ autoPlay: parsed.autoPlay })
      } catch { /* noop */ }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  return {
    prefs: { personaId, autoPlay },
    personas,
    setPersonaId,
    setAutoPlay,
  }
}
