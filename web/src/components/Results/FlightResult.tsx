import type { ReactNode } from 'react'
import { ChevronDown, ExternalLink } from 'lucide-react'
import type { evidenceSources } from '../../utils/flightEvidence'
import './flight-result.css'

export function FlightResult({ agent, kind, title, meta, action, children }: {
  agent: string; kind: string; title: string; meta?: ReactNode; action?: ReactNode; children: ReactNode
}) {
  return <section className="flight-result" data-agent={agent} aria-label={kind}>
    <header className="fdr-heading">
      <div className="fdr-title">
        <p className="fdr-overline"><i /> ALIGO / {kind}</p>
        <h3>{title}</h3>
        {meta && <div className="fdr-meta">{meta}</div>}
      </div>
      {action}
    </header>
    {children}
  </section>
}

export function EvidenceBand({ label, status, children, sources, tone = 'warning', live, stamp = false }: {
  label: string; status: string; children?: ReactNode; sources?: ReturnType<typeof evidenceSources>
  tone?: 'warning' | 'neutral' | 'confirmed'; live?: boolean; stamp?: boolean
}) {
  return <div className="fdr-evidence" data-tone={tone}>
    <div className="fdr-evidence-title" role={live ? 'status' : undefined}>
      <span className="fdr-stamp" data-fresh={stamp || undefined}>{label}</span><strong>{status}</strong>
    </div>
    {children}
    {sources?.length ? <ul aria-label="信息来源" className="fdr-sources">
      <li className="fdr-source-label" aria-hidden="true">来源</li>
      {sources.map(({ title, url }, i) => <li key={i}>
        {url ? <a href={url} target="_blank" rel="noopener noreferrer">{title}<ExternalLink size={13} aria-hidden="true" /></a> : <span>{title}</span>}
      </li>)}
    </ul> : null}
  </div>
}

export function ResultDisclosure({ open, onToggle, controls, children }: {
  open: boolean; onToggle: () => void; controls: string; children: ReactNode
}) {
  return <button type="button" className="fdr-action" aria-expanded={open} aria-controls={controls} onClick={onToggle}>
    {children}<ChevronDown size={15} aria-hidden="true" />
  </button>
}
