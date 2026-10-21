import { CardShell } from './CardShell'

const TYPE_ICONS: Record<string, string> = {
  hotel_brand: '🏨',
  hotel_brands: '🏨',
  hotel: '🏨',
  airline: '✈️',
  airlines: '✈️',
  seat: '💺',
  seat_preference: '💺',
  food: '🍽️',
  dietary: '🍽️',
  transport: '🚕',
  home: '🏠',
  home_location: '🏠',
  city: '🏙️',
  favorite_city: '❤️',
  budget: '💰',
  travel_preference: '🧳',
  weather_preference: '🌤️',
  trip_style: '✨',
}

const TYPE_LABELS: Record<string, string> = {
  hotel_brand: '酒店品牌',
  hotel_brands: '酒店品牌',
  hotel: '酒店偏好',
  airline: '航空公司',
  airlines: '航空公司',
  seat: '座位偏好',
  seat_preference: '座位偏好',
  food: '餐饮偏好',
  dietary: '饮食偏好',
  transport: '出行方式',
  home: '常住城市',
  home_location: '常驻地',
  city: '偏好城市',
  favorite_city: '心仪城市',
  budget: '预算偏好',
  travel_preference: '旅行方式',
  weather_preference: '天气偏好',
  trip_style: '旅行风格',
}

export function PreferenceCard({ data }: { data: Record<string, unknown> }) {
  const raw = data.preferences as unknown
  const prefList = (Array.isArray(raw)
    ? raw
    : (raw as { preferences?: unknown } | undefined)?.preferences) as
    | { type: string; value: string | string[]; action?: string }[]
    | undefined

  return (
    <CardShell agentName="preference">
      <div className="border-b border-rule px-4 py-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-accent">ALIGO / PREFERENCES</div>
        <h4 className="mt-1 text-[15px] font-semibold text-ink">偏好已保存</h4>
      </div>

      <div className="px-4 py-2">
        {!prefList || prefList.length === 0 ? (
          <p className="py-3 text-center text-[12px] text-ink-3">没有识别到新的偏好</p>
        ) : (
          prefList.map((p, i) => (
            <div key={i} className="flex items-start gap-3 border-b border-rule py-2.5 last:border-0">
              <span className="mt-0.5 text-sm" aria-hidden="true">{TYPE_ICONS[p.type] || '⭐'}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[10px] tracking-[0.06em] text-ink-3">{TYPE_LABELS[p.type] || p.type}</div>
                <div className="mt-0.5 text-[13px] leading-6 text-ink">
                  {Array.isArray(p.value) ? p.value.join('、') : p.value}
                </div>
              </div>
              <span className="shrink-0 text-[10px] text-ok">
                {p.action === 'append' ? '已追加' : '已更新'}
              </span>
            </div>
          ))
        )}
      </div>
    </CardShell>
  )
}
