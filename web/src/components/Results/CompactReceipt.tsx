import type { ReactNode } from 'react'
import { ArrowDown, type LucideIcon } from 'lucide-react'

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
  /** lucide 图标组件，取代此前的 emoji 字符串：跨平台字形一致、继承主题色 */
  icon?: LucideIcon
  label: string
  value: string
  sub?: string
  accentColor?: string
}

export function CompactReceiptHero({ icon: Icon, label, value, sub, accentColor }: CompactReceiptHeroProps) {
  return (
    <div className="space-y-1.5 text-center">
      <div className="flex items-center justify-center gap-1.5">
        {Icon && <Icon size={14} strokeWidth={1.5} className="text-ink-3" aria-hidden="true" />}
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

/** 代码芯片：取代国旗 emoji，用于货币代码与语言代码。
 *  票据语境下 ISO 代码比国旗准确（币种跨国流通、语言≠国家），
 *  且等宽字形与本页 mono/tabular 数字体系一致。 */
function CodeChip({ code, tone }: { code: string; tone: 'neutral' | 'accent' }) {
  const toneCls = tone === 'accent' ? 'border-accent/40 text-accent' : 'border-rule text-ink-3'
  return (
    <span
      className={'shrink-0 rounded-[2px] border px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.06em] ' + toneCls}
    >
      {code || '—'}
    </span>
  )
}

interface ExchangeSide {
  /** 货币代码（CNY）或语言代码（zh）；渲染为等宽芯片 */
  code: string
  value: string
  label?: string
  /** 数值场景用等宽+表格数字；译文等散文场景保持正文体 */
  mono?: boolean
}

interface CompactReceiptExchangeProps {
  from: ExchangeSide
  to: ExchangeSide
}

export function CompactReceiptExchange({ from, to }: CompactReceiptExchangeProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-3 rounded-[2px] border border-rule bg-paper-sunken px-3 py-2">
        <CodeChip code={from.code} tone="neutral" />
        <div className="min-w-0 flex-1 text-right">
          <div className={'text-[13px] leading-6 text-ink-2 [overflow-wrap:anywhere] ' + (from.mono ? 'font-mono tabular' : '')}>
            {from.value}
          </div>
          {from.label && <div className="text-[10px] text-ink-3">{from.label}</div>}
        </div>
      </div>

      <div className="flex justify-center text-accent">
        <ArrowDown size={14} strokeWidth={1.5} aria-hidden="true" />
      </div>

      <div className="flex items-start gap-3 rounded-[2px] border border-accent/30 bg-accent-tint px-3 py-2">
        <CodeChip code={to.code} tone="accent" />
        <div className="min-w-0 flex-1 text-right">
          <div className={'leading-6 text-accent [overflow-wrap:anywhere] ' + (to.mono ? 'font-mono text-[16px] font-semibold tabular' : 'text-[13px]')}>
            {to.value}
          </div>
          {to.label && <div className="text-[10px] text-ink-3">{to.label}</div>}
        </div>
      </div>
    </div>
  )
}
