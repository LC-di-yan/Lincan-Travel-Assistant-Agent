import type { Lifecycle } from '../../api/personal'

export const button = 'inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-input border border-rule-strong px-3 text-sm font-semibold text-ink hover:bg-paper-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-route disabled:cursor-default disabled:opacity-60'
export const primary = 'inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-input bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-route disabled:cursor-default disabled:opacity-60'
export const input = 'min-h-11 min-w-0 w-full rounded-input border border-rule-strong bg-paper-raised px-2.5 text-sm text-ink focus-visible:outline-2 focus-visible:outline-route'
export const label = 'grid min-w-0 gap-1.5 text-sm font-medium text-ink-2'
export const pane = 'rounded-card border border-rule bg-paper-raised p-4 sm:p-5'
export const lifecycleLabel: Record<Lifecycle, string> = {
  draft: '草稿', scheduled: '已安排', completed: '已完成', cancelled: '已取消', superseded: '已被替换', archived: '已归档',
}
export const tripHref = (id: string, extra = '') => `#/personal/trips/${id}${extra}`
export const days = (start?: string | null, end?: string | null) => !start ? '日期待定' : end && end !== start ? `${start} 至 ${end}` : start
export const dayTime = (stamp: string) => new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
}).format(new Date(stamp))
