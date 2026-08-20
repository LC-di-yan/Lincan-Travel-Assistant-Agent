import { type ReactNode, useEffect, useRef, useState } from 'react'

/* ── 确认凭条容器 ──────────────────────────────────── */

interface CompactReceiptProps {
  accentColor?: string
  badge?: string
  footer?: string
  footerSecondary?: ReactNode
  children: ReactNode
}

export function CompactReceipt({ accentColor = '#4f8ef7', badge, footer, footerSecondary, children }: CompactReceiptProps) {
  return (
    <div
      className="rounded-2xl overflow-hidden animate-receipt-in receipt-card"
      style={{
        border: '1px solid rgba(180, 150, 120, 0.25)',
        background: 'linear-gradient(135deg, #f3e8db 0%, #ffffff 40%)',
        boxShadow: 'var(--shadow-sm)',
        maxWidth: 380,
      }}
    >
      {/* Badge */}
      {badge && (
        <div className="flex justify-end px-4 pt-3">
          <span
            className="text-[11px] font-medium px-2.5 py-0.5 rounded-full"
            style={{
              backgroundColor: `${accentColor}15`,
              color: accentColor,
            }}
          >
            {badge}
          </span>
        </div>
      )}

      {/* Body */}
      <div className="px-5 py-4">
        {children}
      </div>

      {/* Divider + Footer */}
      {(footer || footerSecondary) && (
        <>
          <div className="px-4">
            <div
              className="border-t border-dashed"
              style={{ borderColor: 'rgba(180, 150, 120, 0.3)' }}
            />
          </div>
          <div className="px-5 py-2.5 flex items-center justify-between">
            {footer && (
              <span className="text-[11px] text-[var(--text-muted)]">{footer}</span>
            )}
            {footerSecondary && (
              <span className="text-[11px] font-medium text-[var(--text-secondary)]">{footerSecondary}</span>
            )}
          </div>
        </>
      )}

      <style>{`
        @keyframes receipt-in {
          0% { opacity: 0; transform: scale(0.96) translateY(4px); }
          60% { transform: scale(1.005); }
          100% { opacity: 1; transform: scale(1) translateY(0); }
        }
        .animate-receipt-in { animation: receipt-in 0.35s cubic-bezier(0.16, 1, 0.3, 1) both; }
        .receipt-card { background: linear-gradient(135deg, #f3e8db 0%, #ffffff 40%) !important; }
        .dark .receipt-card,
        [data-theme="dark"] .receipt-card { background: linear-gradient(135deg, #3d342b 0%, var(--bg-elevated) 40%) !important; border-color: rgba(180, 150, 120, 0.2) !important; }
      `}</style>
    </div>
  )
}

/* ── Hero 布局：emoji label + 大数值 ───────────────── */

interface CompactReceiptHeroProps {
  emoji: string
  label: string
  value: string
  sub?: string
  accentColor?: string
}

export function CompactReceiptHero({ emoji, label, value, sub, accentColor }: CompactReceiptHeroProps) {
  return (
    <div className="text-center space-y-2">
      <div className="flex items-center justify-center gap-1.5">
        <span className="text-base">{emoji}</span>
        <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide">{label}</span>
      </div>
      <AnimatedValue text={value} color={accentColor} />
      {sub && (
        <div className="text-[11px] text-[var(--text-muted)]">{sub}</div>
      )}
    </div>
  )
}

/* ── 汇率/翻译 Exchange 布局：from → to ────────────── */

interface CompactReceiptExchangeProps {
  from: { icon: string; value: string; label?: string }
  to: { icon: string; value: string; label?: string }
}

export function CompactReceiptExchange({ from, to }: CompactReceiptExchangeProps) {
  return (
    <div className="space-y-3">
      {/* From */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-xl" style={{ backgroundColor: 'rgba(243, 232, 219, 0.5)' }}>
        <span className="text-lg">{from.icon}</span>
        <div className="flex-1 text-right">
          <div className="text-sm text-[var(--text-secondary)]">{from.value}</div>
          {from.label && <div className="text-[11px] text-[var(--text-muted)]">{from.label}</div>}
        </div>
      </div>

      {/* Arrow */}
      <div className="flex justify-center">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="2" x2="12" y2="22" />
          <polyline points="7 17 12 22 17 17" />
        </svg>
      </div>

      {/* To */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-xl" style={{ backgroundColor: 'var(--accent-light)', border: '1px solid var(--accent)', borderColor: 'var(--accent)33' }}>
        <span className="text-lg">{to.icon}</span>
        <div className="flex-1 text-right">
          <div className="text-base font-bold text-gradient">{to.value}</div>
          {to.label && <div className="text-[11px] text-[var(--text-muted)]">{to.label}</div>}
        </div>
      </div>
    </div>
  )
}

/* ── 数字滚入动画 ──────────────────────────────────── */

function cascadeChars(text: string): number[] {
  const delays: number[] = []
  const hasDigits = /\d/.test(text)
  for (let i = 0; i < text.length; i++) {
    if (hasDigits && /\d/.test(text[i])) {
      delays.push(100 + i * 40)
    } else {
      delays.push(30 + i * 25)
    }
  }
  return delays
}

function AnimatedValue({ text, color }: { text: string; color?: string }) {
  const [visible, setVisible] = useState(0)
  const delays = useRef(cascadeChars(text))
  const frameRef = useRef<ReturnType<typeof requestAnimationFrame> | null>(null)

  useEffect(() => {
    setVisible(0)
    const start = performance.now()
    const tick = () => {
      const elapsed = performance.now() - start
      let count = 0
      for (const d of delays.current) {
        if (elapsed >= d) count++
      }
      setVisible(count)
      if (count < text.length) {
        frameRef.current = requestAnimationFrame(tick)
      }
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => { if (frameRef.current) cancelAnimationFrame(frameRef.current) }
  }, [text])

  return (
    <div
      className="text-[28px] font-extrabold tracking-tight"
      style={{
        background: color ? `linear-gradient(135deg, ${color}, ${color}cc)` : 'linear-gradient(135deg, var(--accent), #8b5cf6)',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
      }}
    >
      {text.slice(0, visible).split('').map((ch, i) => {
        if (ch === ' ') return <span key={i}>&nbsp;</span>
        const delay = delays.current[i]
        // 数字字符加弹跳
        const isDigit = /\d/.test(ch)
        return (
          <span
            key={i}
            className="inline-block"
            style={{
              animation: isDigit ? `num-pop 0.35s cubic-bezier(0.16, 1, 0.3, 1) ${delay}ms both` : `fade-in 0.2s ease ${delay}ms both`,
              ...(isDigit ? { transformOrigin: 'bottom center' } : {}),
            }}
          >
            {ch}
          </span>
        )
      })}
      <style>{`
        @keyframes num-pop {
          0% { opacity: 0; transform: translateY(8px) scale(0.6); }
          60% { transform: translateY(-1px) scale(1.03); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </div>
  )
}
