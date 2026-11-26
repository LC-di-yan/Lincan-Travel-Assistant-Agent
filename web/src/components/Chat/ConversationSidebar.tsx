import { useEffect, useRef, useState } from 'react'
import { MessageSquareText, Plus, Search, X } from 'lucide-react'
import {
  CONVERSATIONS_CHANGED, ConversationError, deleteConversation, listConversations,
  notifyConversationsChanged, type ConversationPage, type ConversationSummary,
} from '../../api/conversations'
import { HoldToDelete } from '../effects/HoldToDelete'
import { LiquidGlassButton } from '../effects/LiquidGlassButton'

interface Props {
  activeId: string | null
  navigating: boolean
  working: boolean
  onSelect: (id: string) => void
  onNew?: () => void
  onClose?: () => void
  search: string
  onSearch: (value: string) => void
}

const dateLabel = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' })
/** 删除对话的按住时长：破坏性操作，两秒内可随时松手取消。 */
const HOLD_MS = 1500

export function ConversationSidebar({ activeId, navigating, working, onSelect, onNew, onClose, search, onSearch }: Props) {
  const query = search.trim()
  const [version, setVersion] = useState(0)
  const [snapshot, setSnapshot] = useState<{ query: string; version: number; page?: ConversationPage; error?: string }>()
  const [paging, setPaging] = useState(false)
  const [pagingError, setPagingError] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const moreRequest = useRef<AbortController | null>(null)
  const refreshTimer = useRef<number | null>(null)
  const visible = snapshot?.query === query ? snapshot.page : undefined
  const settled = snapshot?.query === query && snapshot.version === version
  const error = settled ? snapshot.error : undefined
  const refresh = () => setVersion((previous) => previous + 1)

  useEffect(() => {
    return () => {
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current)
      refreshTimer.current = null
    }
  }, [])

  useEffect(() => {
    const refreshAfterWrite = () => setVersion((previous) => previous + 1)
    window.addEventListener(CONVERSATIONS_CHANGED, refreshAfterWrite)
    return () => window.removeEventListener(CONVERSATIONS_CHANGED, refreshAfterWrite)
  }, [])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      listConversations(query, null, controller.signal)
        .then((page) => {
          if (!active) return
          setSnapshot({ query, version, page })
          setDeleting((current) => (current && !page.items.some((row) => row.id === current) ? null : current))
        })
        .catch((err: unknown) => {
          if (active) setSnapshot((previous) => ({
            query, version, page: previous?.query === query ? previous.page : undefined,
            error: err instanceof ConversationError ? err.message : '暂时无法读取聊天记录。',
          }))
        })
    }, query ? 240 : 0)
    const timeout = window.setTimeout(() => controller.abort(), 8000)
    return () => {
      active = false
      window.clearTimeout(timer)
      window.clearTimeout(timeout)
      controller.abort()
      const paginated = moreRequest.current
      if (paginated && !paginated.signal.aborted) paginated.abort()
    }
  }, [query, version])

  const loadMore = async () => {
    const before = visible?.next_before
    if (paging || before == null) return
    const controller = new AbortController()
    moreRequest.current = controller
    const timer = window.setTimeout(() => controller.abort('timeout'), 8000)
    setPaging(true)
    setPagingError('')
    try {
      const page = await listConversations(query, before, controller.signal)
      setSnapshot((previous) => {
        if (previous?.query !== query || previous.version !== version || !previous.page || controller.signal.aborted) return previous
        const seen = new Set(previous.page.items.map((row) => row.id))
        return { query, version, page: { ...page, items: [...previous.page.items, ...page.items.filter((row) => !seen.has(row.id))] } }
      })
    } catch {
      if (!controller.signal.aborted || controller.signal.reason === 'timeout') setPagingError('暂时无法加载更多，点击重试。')
    } finally {
      window.clearTimeout(timer)
      if (moreRequest.current === controller) {
        moreRequest.current = null
        setPaging(false)
      }
    }
  }

  const removeConversation = async (row: ConversationSummary) => {
    setDeleting(row.id)
    setDeleteError('')
    try {
      await deleteConversation(row.id)
      if (row.id === activeId) onNew?.()
      // 渐隐已经在卡片里走完，这里直接把它从列表摘掉，再让侧栏与别处对齐。
      setSnapshot((previous) => previous?.page
        ? { ...previous, page: { ...previous.page, items: previous.page.items.filter((item) => item.id !== row.id) } }
        : previous)
      setDeleting(null)
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current)
      refreshTimer.current = window.setTimeout(() => {
        refreshTimer.current = null
        notifyConversationsChanged()
        refresh()
      }, 300)
    } catch (err) {
      setDeleting(null)
      setDeleteError(err instanceof ConversationError ? err.message : '删除失败，请稍后重试。')
    }
  }

  return (
    <nav id="conversation-history" aria-label="聊天记录" className="flex h-full min-h-0 min-w-0 flex-col bg-paper-sunken">
      <div className="shrink-0 space-y-2.5 border-b border-rule px-3 pb-3 pt-2">
        <div className="flex min-h-9 items-center justify-between gap-2 pl-1">
          <h2 className="text-sm font-semibold text-ink">聊天记录</h2>
          {onClose && <button type="button" aria-label="关闭聊天记录" onClick={onClose} autoFocus
            className="flex h-11 w-11 items-center justify-center rounded-input text-ink-2 hover:bg-paper">
            <X size={17} aria-hidden="true" />
          </button>}
        </div>
        {onNew && <button type="button" onClick={onNew} disabled={navigating}
          className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-input border border-rule-strong bg-paper text-sm font-semibold text-ink hover:border-accent hover:text-accent disabled:opacity-50">
          <Plus size={15} aria-hidden="true" /> 新建对话
        </button>}
        <label className="flex min-h-11 items-center gap-2 rounded-input border border-rule bg-paper px-2.5 focus-within:border-accent">
          <Search size={15} className="shrink-0 text-ink-3" aria-hidden="true" />
          <input type="search" aria-label="搜索聊天记录" placeholder="搜索聊天记录" value={search} maxLength={100}
            onChange={(event) => { onSearch(event.target.value); setPagingError('') }}
            onKeyDown={event => {
              if (event.key === 'Escape' && onClose) { event.preventDefault(); onClose() }
            }}
            className="w-full min-w-0 bg-transparent py-1 text-sm text-ink outline-none placeholder:text-ink-3" />
        </label>
        {deleteError && <p role="alert" className="px-1 text-xs leading-5 text-[#e58a80]">{deleteError}</p>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-2">
        {error && <p className="px-2 py-2 text-xs leading-5 text-ink-2" role="status">
          {error} <button type="button" className="min-h-9 font-semibold text-accent underline" onClick={refresh}>重试</button>
        </p>}
        {!settled && !visible && <p role="status" className="px-2 py-3 text-xs text-ink-2">正在查找聊天记录…</p>}
        {settled && !error && !visible?.items.length && (
          <p role="status" className="px-2 py-3 text-xs leading-5 text-ink-2">
            {query ? '没有找到匹配的对话。' : '发出第一条消息后，对话会保存在这里。'}
          </p>
        )}
        {!!visible?.items.length && (
          <ul className="chart-paper conversation-list space-y-2 pb-2">
            {visible.items.map((row) => {
              const active = row.id === activeId
              const updated = row.updated_at ? Date.parse(row.updated_at) : NaN
              const content = <span className="lg-content lg-content--row">
                <MessageSquareText size={15} strokeWidth={1.8} aria-hidden="true" className="lg-row-icon" />
                <span className="lg-text">
                  <span className="lg-title" title={row.title}>{row.title}</span>
                  <span className="lg-row-line">
                    <span className="lg-subtitle">{row.readonly ? '只读归档' : row.preview}</span>
                    {Number.isFinite(updated) && <time dateTime={row.updated_at!} className="lg-meta">{dateLabel.format(updated)}</time>}
                  </span>
                </span>
              </span>
              return <li key={row.id}>
                {row.readonly
                  ? <LiquidGlassButton
                    className="lg-fill"
                    title={row.title}
                    active={active}
                    ariaLabel={'打开只读对话：' + row.title}
                    onClick={() => { if (!navigating) onSelect(row.id) }}>
                    {content}
                  </LiquidGlassButton>
                  : <HoldToDelete
                    surface="glass"
                    width="100%"
                    height={64}
                    holdMs={HOLD_MS}
                    align="left"
                    active={active}
                    deleted={deleting === row.id}
                    deletedLabel="已删除"
                    ariaLabel={'按住 ' + (HOLD_MS / 1000) + ' 秒删除对话：' + row.title}
                    onActivate={() => { if (!navigating) onSelect(row.id) }}
                    onConfirm={() => { void removeConversation(row) }}>
                    {content}
                  </HoldToDelete>}
              </li>
            })}
          </ul>
        )}
        {visible?.next_before != null && (
          <button type="button" onClick={() => void loadMore()} disabled={paging || !settled}
            className="mt-1 min-h-11 w-full rounded-input text-xs text-ink-2 hover:bg-paper disabled:opacity-50">
            {paging ? '正在加载…' : pagingError || '更多对话'}
          </button>
        )}
      </div>
      {working && <p className="border-t border-rule px-3 py-2 text-[11px] leading-5 text-ink-2">切换会停止当前生成，已保存的消息不会删除。</p>}
    </nav>
  )
}
