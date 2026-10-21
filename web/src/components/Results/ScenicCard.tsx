import { PlaceListCard } from './PlaceListCard'
import type { ScenicItem } from '../../api/types'

export function ScenicCard({ data }: { data: Record<string, unknown> }) {
  const results = (data.results || data) as Record<string, unknown>
  const attractions = (results.attractions || []) as ScenicItem[]
  const sources = (results.sources || data.sources) as { title: string; url: string }[] | undefined

  return (
    <PlaceListCard
      agentName="scenic_search"
      eyebrow="ALIGO / SEE"
      city={(results.city as string) || ''}
      keyword={(results.keyword as string) || '景点'}
      unit="个"
      summary={(results.summary as string) || ''}
      items={attractions}
      count={(results.count as number) || 0}
      sources={sources}
      emptyText="未找到相关景点信息，请尝试更换城市或关键词"
      error={data.error}
    />
  )
}
