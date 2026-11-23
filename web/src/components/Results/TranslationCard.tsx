import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { EvidenceBand, FlightResult } from './FlightResult'
import { evidenceSources, evidenceText } from '../../utils/flightEvidence'

export function TranslationCard({ data }: { data: Record<string, unknown> }) {
  const [copyState, setCopyState] = useState<'ready' | 'copied' | 'failed'>('ready')
  const source = typeof data.source_text === 'string' ? data.source_text : ''
  const translated = typeof data.translated_text === 'string' ? data.translated_text : ''
  const languages = [evidenceText(data.source_lang), evidenceText(data.target_lang)].filter(Boolean).join(' → ')
  const sources = evidenceSources(data.sources)
  if (data.action === 'error' || !source || !translated) return <FlightResult kind="翻译回执" agent="translation" title="翻译未完成">
    <EvidenceBand label="未完成" status={evidenceText(data.answer) || '尚无可复制的译文'} sources={sources} />
  </FlightResult>
  const copy = async () => {
    try { await navigator.clipboard.writeText(translated); setCopyState('copied') }
    catch { setCopyState('failed') }
  }
  return <FlightResult kind="翻译回执" agent="translation" title="翻译结果" meta={languages || undefined}>
    {sources.length > 0 && <EvidenceBand label="资料" status="翻译来源" tone="neutral" sources={sources} />}
    <div className="fdr-summary">
      <h4 className="font-semibold text-ink">译文</h4>
      <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{translated}</p>
      <button type="button" className="fdr-action" onClick={() => void copy()}>
        {copyState === 'copied' ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
        复制译文
      </button>
      <p role="status">{copyState === 'copied' ? '已复制译文' : copyState === 'failed' ? '未能复制，请手动选取译文。' : ''}</p>
      <details className="border-t border-rule">
        <summary className="min-h-11 cursor-pointer py-3 font-semibold">查看原文</summary>
        <p className="whitespace-pre-wrap text-sm">{source}</p>
      </details>
    </div>
  </FlightResult>
}
