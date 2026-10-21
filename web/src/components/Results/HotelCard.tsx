import { PlaceListCard } from './PlaceListCard'
import type { HotelItem } from '../../api/types'

export function HotelCard({ data }: { data: Record<string, unknown> }) {
  const results = (data.results || data) as Record<string, unknown>
  const hotels = (results.hotels || []) as HotelItem[]
  const sources = (results.sources || data.sources) as { title: string; url: string }[] | undefined

  return (
    <PlaceListCard
      agentName="hotel_search"
      eyebrow="ALIGO / STAY"
      city={(results.city as string) || ''}
      keyword={(results.keyword as string) || '酒店'}
      unit="家"
      summary={(results.summary as string) || ''}
      items={hotels}
      count={(results.count as number) || 0}
      sources={sources}
      emptyText="未找到相关住宿信息，请尝试更换城市或关键词"
      error={data.error}
    />
  )
}
