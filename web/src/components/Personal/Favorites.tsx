import { useCallback, useState } from 'react'
import { type Favorite, type FavoriteKind, type PlanRef, personalApi } from '../../api/personal'
import { useChatStore } from '../../store/chatStore'
import { Section, StableResourceRegion } from './ui'
import { button, dayTime, pane, tripHref } from './style'
import { usePersonalResource } from './usePersonalResource'

const kindText: Record<FavoriteKind, string> = { plan: '行程', rail: '铁路', hotel: '住宿', place: '地点' }

export function FavoriteButton({ kind, source, option, direction, children }: {
  kind: FavoriteKind; source: PlanRef; option?: string; direction?: 'outbound' | 'inbound'; children?: string
}) {
  const [state, setState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [error, setError] = useState('')
  return <span className="inline-flex flex-wrap items-center gap-2">
    <button type="button" className={button} disabled={state !== 'idle'} onClick={async () => {
      setState('busy'); setError('')
      try { await personalApi.saveFavorite(kind, source, option, direction); setState('done') }
      catch (err) { setError(err instanceof Error ? err.message : '收藏未保存。'); setState('idle') }
    }}>{state === 'done' ? `已收藏${kindText[kind]}` : state === 'busy' ? '正在收藏…' : children || `收藏${kindText[kind]}`}</button>
    {error && <span role="alert" className="text-xs text-err">{error}</span>}
  </span>
}

function suggestion(item: Favorite) {
  const s = item.snapshot
  if (item.kind === 'rail' && s.origin && s.destination) return `请查询从${s.origin}到${s.destination}的直达火车余票，优先看${s.service}。`
  if (s.city && item.title && item.kind !== 'plan') return `帮我查询${s.city}的${item.title}的位置和当前可核对信息。`
  return null
}

export default function Favorites() {
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState('')
  const [operationError, setError] = useState('')
  const loader = useCallback((signal: AbortSignal) => personalApi.favorites(offset, signal), [offset])
  const { data, error, loading, retry } = usePersonalResource(loader)

  return <Section className="trip-header" title="已收藏资料">
    <p className="text-sm leading-6 text-ink-3">收藏留的是资料线索。日期、车次、余票和房价可能变化，重新使用前请查证。</p>
    <StableResourceRegion holding={loading || !!error}>
    {(error || operationError) && <div className={`${pane} mt-3`}><p role="alert" className="text-sm text-err">{error || operationError}</p>
      <button type="button" className={`${button} mt-2`} onClick={() => { setError(''); retry() }}>重新读取</button></div>}
    {loading && <p role="status" className="mt-3 text-sm text-ink-3">正在读取收藏…</p>}
    {data?.items.length === 0 && <p className="mt-4 text-sm text-ink-2">还没有收藏。你可以在已保存行程中收藏一个版本、交通方案或住宿。</p>}
    <ul className="divide-y divide-rule">
      {data?.items.map((item) => {
        const prompt = suggestion(item)
        return <li key={item.favorite_id} className="flex flex-wrap items-center gap-x-5 gap-y-2 py-3">
          <div className="min-w-0 flex-1 basis-44">
            <p className="break-words text-sm font-semibold">{item.title}</p>
            <p className="text-xs leading-5 text-ink-3">{kindText[item.kind]} · 来源：行程第 {item.ref.version} 版{item.suggest_recheck ? ' · 历史快照，使用前重查' : ''}</p>
            <p className="text-xs leading-5 text-ink-3">收藏于 {dayTime(item.created_at)}（北京时间）</p>
            {item.kind === 'rail' && item.snapshot.departed_at && <p className="text-xs text-ink-3">{item.snapshot.origin} → {item.snapshot.destination} · 当时的计划 {dayTime(item.snapshot.departed_at)}</p>}
          </div>
          <a className={button} href={tripHref(item.ref.plan_id, `?v=${item.ref.version}`)}>查看原版本</a>
          {prompt && <a className={button} href="#/" onClick={() => useChatStore.getState().setDraftPrompt(prompt)}>到对话重新查询</a>}
          <button type="button" className={button} disabled={!!busy} onClick={async () => {
            setBusy(item.favorite_id); setError('')
            try { await personalApi.dropFavorite(item.favorite_id); retry() }
            catch (err) { setError(err instanceof Error ? err.message : '取消收藏失败。') }
            finally { setBusy('') }
          }}>{busy === item.favorite_id ? '正在移除…' : '取消收藏'}</button>
        </li>
      })}
    </ul>
    <div className="mt-2 flex flex-wrap gap-2">
      {offset > 0 && <button type="button" className={button} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</button>}
      {data?.next_offset != null && <button type="button" className={button} onClick={() => setOffset(data.next_offset ?? 0)}>下一页</button>}
    </div>
    </StableResourceRegion>
  </Section>
}
