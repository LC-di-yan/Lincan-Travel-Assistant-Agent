import { PlaceListCard } from './PlaceListCard'
import type { RestaurantItem } from '../../api/types'

export function RestaurantCard({ data }: { data: Record<string, unknown> }) {
  const results = (data.results || data) as Record<string, unknown>
  const restaurants = (results.restaurants || []) as RestaurantItem[]
  const sources = (results.sources || data.sources) as { title: string; url: string }[] | undefined

  return (
    <PlaceListCard
      agentName="restaurant_search"
      eyebrow="ALIGO / DINING"
      city={(results.city as string) || ''}
      keyword={(results.keyword as string) || '美食'}
      unit="家"
      summary={(results.summary as string) || ''}
      items={restaurants}
      count={(results.count as number) || 0}
      sources={sources}
      emptyText="未找到相关餐厅信息，请尝试更换城市或菜系关键词"
      error={data.error}
    />
  )
}
