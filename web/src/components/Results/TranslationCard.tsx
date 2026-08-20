import { useState } from 'react'
import { CompactReceipt, CompactReceiptExchange } from './CompactReceipt'
import { getAgentColor } from '../Icons'
import { Copy, Check } from 'lucide-react'

const FLAGS: Record<string, string> = {
  zh: '\u{1F1E8}\u{1F1F3}', en: '\u{1F1EC}\u{1F1E7}', ja: '\u{1F1EF}\u{1F1F5}',
  ko: '\u{1F1F0}\u{1F1F7}', fr: '\u{1F1EB}\u{1F1F7}', de: '\u{1F1E9}\u{1F1EA}',
  es: '\u{1F1EA}\u{1F1F8}', ru: '\u{1F1F7}\u{1F1FA}', th: '\u{1F1F9}\u{1F1ED}',
  vi: '\u{1F1FB}\u{1F1F3}', ar: '\u{1F1F8}\u{1F1E6}', pt: '\u{1F1F5}\u{1F1F9}',
  it: '\u{1F1EE}\u{1F1F9}',
}

const accent = getAgentColor('translation')

export function TranslationCard({ data }: { data: Record<string, unknown> }) {
  const [copied, setCopied] = useState(false)
  const action = data.action as string
  const sourceText = data.source_text as string || ''
  const translatedText = data.translated_text as string || ''
  const sourceLang = data.source_lang as string || ''
  const targetLang = data.target_lang as string || ''

  if (action === 'error' || !sourceText) {
    return (
      <CompactReceipt accentColor="#ef4444">
        <p className="text-sm text-center text-[var(--error)] py-2">{data.answer as string || '翻译失败'}</p>
      </CompactReceipt>
    )
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(translatedText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <CompactReceipt
      accentColor={accent}
      footer={`${FLAGS[sourceLang] || ''} ${sourceLang} → ${FLAGS[targetLang] || ''} ${targetLang}`}
      footerSecondary={
        <button onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full transition-colors hover:bg-[var(--bg-secondary)]"
          style={{ color: 'var(--accent)' }}>
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? '已复制' : '复制'}
        </button>
      }
    >
      <CompactReceiptExchange
        from={{ icon: FLAGS[sourceLang] || '\u{1F310}', value: sourceText }}
        to={{ icon: FLAGS[targetLang] || '\u{1F310}', value: translatedText }}
      />
    </CompactReceipt>
  )
}
