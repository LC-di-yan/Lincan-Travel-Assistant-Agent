import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'
import { ArrowRight, Copy, Check } from 'lucide-react'
import { useState } from 'react'

const LANG_FLAGS: Record<string, string> = {
  zh: '🇨🇳', en: '🇬🇧', ja: '🇯🇵', ko: '🇰🇷', fr: '🇫🇷',
  de: '🇩🇪', es: '🇪🇸', ru: '🇷🇺', th: '🇹🇭', vi: '🇻🇳',
  ar: '🇸🇦', pt: '🇵🇹', it: '🇮🇹',
}

const LANG_NAMES: Record<string, string> = {
  zh: '中文', en: '英文', ja: '日文', ko: '韩文', fr: '法文',
  de: '德文', es: '西班牙文', ru: '俄文', th: '泰文', vi: '越南文',
  ar: '阿拉伯文', pt: '葡萄牙文', it: '意大利文',
}

export function TranslationCard({ data }: { data: Record<string, unknown> }) {
  const [copied, setCopied] = useState(false)
  const action = data.action as string
  const sourceText = data.source_text as string || ''
  const translatedText = data.translated_text as string || ''
  const sourceLang = data.source_lang as string || ''
  const targetLang = data.target_lang as string || ''
  const answer = data.answer as string || ''

  if (action === 'error') {
    return (
      <CardShell agentName="translation">
        <div className="p-4">
          <h4 className="font-semibold text-sm flex items-center gap-1.5 mb-2">
            <AgentIcon agentName="translation" size={16} />
            翻译
          </h4>
          <p className="text-sm text-[var(--error)]">{answer}</p>
        </div>
      </CardShell>
    )
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(translatedText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <CardShell agentName="translation">
      <div className="p-4 space-y-3">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="translation" size={16} />
          翻译结果
        </h4>

        {/* Language indicator */}
        <div className="flex items-center justify-center gap-2 text-xs text-[var(--text-muted)]">
          <span>{LANG_FLAGS[sourceLang] || '🌐'} {LANG_NAMES[sourceLang] || sourceLang}</span>
          <ArrowRight size={14} />
          <span>{LANG_FLAGS[targetLang] || '🌐'} {LANG_NAMES[targetLang] || targetLang}</span>
        </div>

        {/* Source text */}
        <div className="p-3 rounded-xl text-sm" style={{ backgroundColor: 'var(--bg-secondary)' }}>
          <div className="text-xs text-[var(--text-muted)] mb-1">原文</div>
          <div className="text-[var(--text-secondary)]">{sourceText}</div>
        </div>

        {/* Translated text */}
        <div className="p-3 rounded-xl relative group" style={{ backgroundColor: 'var(--accent-light)' }}>
          <div className="text-xs text-[var(--accent)] mb-1">译文</div>
          <div className="text-sm font-medium pr-8">{translatedText}</div>
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1.5 rounded-lg opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity"
            style={{ backgroundColor: 'var(--bg-elevated)' }}
            title="复制译文"
          >
            {copied ? <Check size={12} className="text-[var(--success)]" /> : <Copy size={12} className="text-[var(--text-muted)]" />}
          </button>
        </div>

        {answer && <p className="text-xs text-[var(--text-secondary)]">{answer}</p>}
      </div>
    </CardShell>
  )
}
