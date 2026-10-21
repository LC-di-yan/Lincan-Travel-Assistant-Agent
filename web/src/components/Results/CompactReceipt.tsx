import type { ReactNode } from 'react'

interface CompactReceiptProps {
  accentColor?: string
  eyebrow?: string
  title?: string
  badge?: string
  footer?: string
  footerSecondary?: ReactNode
  children: ReactNode
}

export function CompactReceipt({
  accentColor = 'var(--accent)',
  eyebrow,
  title,
  badge,
  footer,
  footerSecondary,
  children,
}: CompactReceiptProps) {
  const badgeNode = badge ? (
    <span
      className="shrink-0 rounded-[2px] border px-2 py-0.5 font-mono text-[10px] tracking-[0.04em]"
      style={{ borderColor: accentColor, color: accentColor }}
    >
      {badge}
    </span>
  ) : null

  return (
    <div
      className="w-full overflow-hidden rounded-[2px] border border-rule bg-paper-raised"
      style={{ maxWidth: 520 }}
    >
      {(eyebrow || title) ? (
        <div className="flex items-start justify-between gap-3 border-b border-rule px-4 py-3">
          <div className="min-w-0">
            {eyebrow && <div className="font-mono text-[10px] tracking-[0.14em] text-accent">{eyebrow}</div>}
            {title && <div className="mt-1 text-[13px] font-semibold text-ink">{title}</div>}
          </div>
          {badgeNode}
        </div>
      ) : (
        badgeNode && <div className="flex justify-end px-4 pt-3">{badgeNode}</div>
      )}

      <div className="px-4 py-3">{children}</div>

      {(footer || footerSecondary) && (
        <>
          <div className="mx-4 border-t border-dashed border-rule" />
          <div className="flex items-center justify-between px-4 py-2.5">
            {footer && <span className="text-[11px] text-ink-3">{footer}</span>}
            {footerSecondary && (
              <span className="font-mono text-[11px] font-medium tabular text-ink-2">
                {footerSecondary}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}

interface CompactReceiptHeroProps {
  emoji: string
  label: string
  value: string
  sub?: string
  accentColor?: string
}

export function CompactReceiptHero({ emoji, label, value, sub, accentColor }: CompactReceiptHeroProps) {
  return (
    <div className="space-y-1.5 text-center">
      <div className="flex items-center justify-center gap-1.5">
        <span className="text-sm" aria-hidden="true">{emoji}</span>
        <span className="text-[11px] uppercase tracking-[0.08em] text-ink-3">{label}</span>
      </div>
      <div
        className="font-mono text-[26px] font-semibold tabular tracking-tight"
        style={{ color: accentColor || 'var(--accent)' }}
      >
        {value}
      </div>
      {sub && <div className="text-[11px] text-ink-3">{sub}</div>}
    </div>
  )
}

interface CompactReceiptExchangeProps {
  from: { icon: string; value: string; label?: string }
  to: { icon: string; value: string; label?: string }
}

export function CompactReceiptExchange({ from, to }: CompactReceiptExchangeProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 rounded-[2px] border border-rule bg-paper-sunken px-3 py-2">
        <span className="text-base" aria-hidden="true">{from.icon}</span>
        <div className="flex-1 text-right">
          <div className="text-[13px] text-ink-2">{from.value}</div>
          {from.label && <div className="text-[10px] text-ink-3">{from.label}</div>}
        </div>
      </div>

      <div className="flex justify-center text-accent" aria-hidden="true">↓</div>

      <div className="flex items-center gap-3 rounded-[2px] border border-accent/30 bg-accent-tint px-3 py-2">
        <span className="text-base" aria-hidden="true">{to.icon}</span>
        <div className="flex-1 text-right">
          <div className="font-mono text-[16px] font-semibold tabular text-accent">{to.value}</div>
          {to.label && <div className="text-[10px] text-ink-3">{to.label}</div>}
        </div>
      </div>
    </div>
  )
}
