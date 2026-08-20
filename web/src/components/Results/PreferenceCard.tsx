import { CompactReceipt, CompactReceiptHero } from './CompactReceipt'
import { getAgentColor } from '../Icons'

const TYPE_ICONS: Record<string, string> = {
  hotel_brand: '\u{1F3E8}',
  hotel: '\u{1F3E8}',
  airline: '\u{2708}',
  seat: '\u{1F4BA}',
  food: '\u{1F37D}',
  transport: '\u{1F695}',
  home: '\u{1F3E0}',
  city: '\u{1F3D9}',
  budget: '\u{1F4B0}',
}

const TYPE_LABELS: Record<string, string> = {
  hotel_brand: '酒店品牌',
  hotel: '酒店偏好',
  airline: '航空公司',
  seat: '座位偏好',
  food: '餐饮偏好',
  transport: '出行方式',
  home: '常住城市',
  city: '偏好城市',
  budget: '预算偏好',
}

const accent = getAgentColor('preference')

export function PreferenceCard({ data }: { data: Record<string, unknown> }) {
  const prefs = data.preferences as Record<string, unknown> | undefined
  const prefList = prefs?.preferences as { type: string; value: string; action?: string }[] | undefined

  if (!prefList || prefList.length === 0) {
    return (
      <CompactReceipt accentColor={accent} badge="✓ 已保存">
        <p className="text-sm text-center text-[var(--text-secondary)] py-2">偏好已保存</p>
      </CompactReceipt>
    )
  }

  return (
    <div className="space-y-2 animate-receipt-in">
      {prefList.map((p, i) => {
        const icon = TYPE_ICONS[p.type] || '\u{2B50}'
        const typeLabel = TYPE_LABELS[p.type] || p.type
        return (
          <CompactReceipt
            key={i}
            accentColor={accent}
            badge="✓ 已记住"
            footer={p.action === 'append' ? '\u{2795} 追加到已有偏好' : '\u{1F504} 已更新偏好'}
          >
            <CompactReceiptHero
              emoji={icon}
              label={typeLabel}
              value={p.value}
              accentColor={accent}
            />
          </CompactReceipt>
        )
      })}
    </div>
  )
}
