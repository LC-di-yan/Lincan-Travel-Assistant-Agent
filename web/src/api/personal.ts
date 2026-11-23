import { ensureIdentity } from './client'

export interface PlanRef { plan_id: string; version: number }
export interface PlanLink { ref: PlanRef; title: string }
export interface PersonalCaps { enabled: boolean; csrf_token: string | null }
export type Lifecycle = 'draft' | 'scheduled' | 'completed' | 'cancelled' | 'superseded' | 'archived'
export interface ActionReceipt { plan_id: string; version: number; revision: number; lifecycle: Lifecycle }
export interface PlanMeta {
  plan_id: string
  title: string
  lifecycle: Lifecycle
  revision: number
  current_draft_version: number
  scheduled_version: number | null
  scheduled_start_date?: string | null
  scheduled_end_date?: string | null
  start_date: string | null
  end_date: string | null
  origin: string | null
  destination: string | null
  quality: 'structured' | 'partial' | 'manual'
  created_at: string
  updated_at: string
}
export interface PlanEvent {
  event_id?: string
  title: string
  kind: 'rail' | 'flight' | 'meeting' | 'check_in' | 'check_out' | 'activity' | 'buffer'
  commitment: 'fixed' | 'soft'
  precision: 'exact' | 'window' | 'date_only' | 'unknown'
  timezone: 'Asia/Shanghai'
  start_at?: string | null
  end_at?: string | null
  local_date?: string | null
  end_date?: string | null
  city?: string | null
  arrival_city?: string | null
  place?: string | null
  arrival_place?: string | null
  notes?: string
  before_minutes?: number
  after_minutes?: number
}
export interface DraftContent {
  title: string
  origin?: string | null
  destination?: string | null
  start_date?: string | null
  end_date?: string | null
  schedule_items?: PlanEvent[]
  notes?: string
  budget?: { amount: string; currency: string } | null
}
export interface PlanOption {
  option_id: string
  status: 'validated' | 'provisional'
  schedule_items: PlanEvent[]
  hotel: string | null
  hotel_ref: string | null
  hotel_reference_cny: string[]
  quotes: { price: { amount: string; currency: string }; unit: string; queried_at: string; valid_until: string; source_url: string }[]
  observations: { kind: 'outbound_rail' | 'inbound_rail' | 'hotel_place'; source_url: string; observed_at: string | null }[]
  commute: { from_place: string; to_place: string; minutes: number; source_url: string; queried_at: string } | null
  known_subtotals: Record<string, string>
  reasons: string[]
}
export interface PlanSnapshot extends DraftContent {
  source_kind: 'typed' | 'legacy' | 'manual' | 'imported_summary'
  quality: PlanMeta['quality']
  selected_option_id: string | null
  options: PlanOption[]
  issues: string[]
  raw_estimate: string | null
  based_on: PlanRef | null
}
export interface VersionInfo { version: number; parent_version: number | null; created_at: string }
export interface PlanVersion extends VersionInfo { snapshot: PlanSnapshot }
export interface TripDetail { plan: PlanMeta; draft: PlanVersion; scheduled: PlanVersion | null }
export interface Overview { today: string; upcoming: PlanMeta[]; recent_drafts: PlanMeta[]; frequent_destinations: { city: string; count: number }[]; counts: { draft: number; scheduled: number } }
export interface LegacyTrip { trip_id: string; ambiguous: boolean; origin: string | null; destination: string | null; start_date: string | null; end_date: string | null }

export type CandidateContent = { source: 'candidate'; candidate_ref: string; session_id: string; option_id?: string }
export type ManualContent = { source: 'manual'; draft: DraftContent }
export type VersionContent = CandidateContent | ManualContent | { source: 'saved_version' } | { source: 'saved_option'; option_id: string }
export type CreateContent = CandidateContent | ManualContent | { source: 'copy'; ref: PlanRef } | { source: 'historical_summary'; trip_id: string }
export type ScheduleAction = 'schedule' | 'reschedule' | 'replace' | 'cancel' | 'archive' | 'complete'
export interface Replacement extends PlanRef { revision: number; title?: string }
export interface ConflictIssue {
  id: string; code: string; severity: 'definite' | 'potential' | 'unknown'; message: string
  requires_ack: boolean; blocks_schedule: boolean; other: Replacement | null
}
export interface ConflictReport { calendar_revision: number; rule_version: number; issues: ConflictIssue[]; can_commit: boolean }
export interface OperationPreview { action: ScheduleAction; operation_id: string | null; expires_at: string | null; report: ConflictReport; replacements: Replacement[] }
export type CurrencyTotals = Record<string, string>
export interface ExpenseLine {
  entry_ref: string; trip_plan_id: string | null; amount: string; currency: string; category: string
  description: string; date: string | null; timestamp: string; revision: string
}
export interface ExpenseReport {
  items: ExpenseLine[]; count: number; next_offset: number | null; totals_by_currency: CurrencyTotals
  by_category: Record<string, CurrencyTotals>; by_month: Record<string, CurrencyTotals>; by_year: Record<string, CurrencyTotals>
  invalid_count: number; unknown_date_count: number
}
export interface ExpenseAssignment {
  operation_id: string; expires_at: string; amount: string; currency: string; before_title: string | null; after_title: string | null
}
export type PreferenceValue = string | string[] | { amount: string; currency: string } | null
export interface PreferenceItem { key: string; label: string; value: PreferenceValue; use_for_planning: boolean; supported_for_planning: boolean }
export interface PreferencesView { items: PreferenceItem[]; enabled: boolean; revision: string }
export type FavoriteKind = 'plan' | 'rail' | 'hotel' | 'place'
export interface Favorite {
  favorite_id: string; kind: FavoriteKind; title: string; created_at: string; ref: PlanRef; suggest_recheck: boolean
  snapshot: { [key: string]: string | null | undefined }
}

let capability: Promise<PersonalCaps> | null = null

export function personalCapabilities(refresh = false): Promise<PersonalCaps> {
  if (!capability || refresh) {
    capability = call<PersonalCaps>('/capabilities').catch((error) => {
      capability = null
      throw error
    })
  }
  return capability
}

export class PersonalError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'PersonalError'
    this.status = status
    this.code = code
  }
}

export const newOperationKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')

async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
  await ensureIdentity()
  const response = await fetch(`/api/personal${path}`, { ...options, credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const invalid = Array.isArray(detail?.detail) ? detail.detail.find((item: { msg?: string }) => item?.msg)?.msg : null
    throw new PersonalError(
      detail?.message || (typeof detail?.detail === 'string' && detail.detail) || (invalid ? `请检查输入：${invalid.replace(/^Value error, /, '')}` : '') || '个人中心暂时无法读取，请重试。',
      response.status, detail?.code,
    )
  }
  return response.json() as Promise<T>
}

async function write<T>(path: string, method: string, data: unknown, key?: string, revision?: number) {
  let csrf = (await personalCapabilities()).csrf_token
  if (!csrf) csrf = (await personalCapabilities(true)).csrf_token
  if (!csrf) throw new Error('当前站点未开放个人中心。')
  const headers: Record<string, string> = { 'Content-Type': 'application/json', 'X-Aligo-CSRF': csrf }
  if (key) headers['Idempotency-Key'] = key
  if (revision != null) headers['If-Match'] = `"${revision}"`
  return call<T>(path, { method, headers, body: JSON.stringify(data) })
}

export const personalApi = {
  overview: (signal?: AbortSignal) => call<Overview>('/overview', { signal }),
  legacy: (signal?: AbortSignal) => call<{ items: LegacyTrip[] }>('/legacy-trips', { signal }),
  list: (params = new URLSearchParams(), signal?: AbortSignal) => call<{ items: PlanMeta[]; next_cursor: string | null }>(`/trips?${params}`, { signal }),
  get: (id: string, signal?: AbortSignal) => call<TripDetail>(`/trips/${encodeURIComponent(id)}`, { signal }),
  versions: (id: string, signal?: AbortSignal) => call<{ items: VersionInfo[] }>(`/trips/${encodeURIComponent(id)}/versions`, { signal }),
  version: (id: string, version: number, signal?: AbortSignal) => call<PlanVersion>(`/trips/${encodeURIComponent(id)}/versions/${version}`, { signal }),
  create: (content: CreateContent, key: string) => write<ActionReceipt>('/trips', 'POST', content, key),
  addVersion: (ref: PlanRef, content: VersionContent, revision: number, key: string) => write<ActionReceipt>(
    `/trips/${encodeURIComponent(ref.plan_id)}/versions`, 'POST', { based_on_version: ref.version, content }, key, revision,
  ),
  rename: (id: string, title: string, revision: number) => write<PlanMeta>(`/trips/${encodeURIComponent(id)}`, 'PATCH', { title }, undefined, revision),
  conflicts: (ref: string, session: string) => call<ConflictReport>(`/candidates/${encodeURIComponent(ref)}/conflicts?${new URLSearchParams({session_id: session})}`),
  preview: (id: string, action: ScheduleAction, draftVersion: number, revision: number, refs: Replacement[] = []) => write<OperationPreview>(
    `/trips/${encodeURIComponent(id)}/operations/preview`, 'POST', {
      action, draft_version: draftVersion, expected_revision: revision,
      replace_refs: refs.map(({ plan_id, version, revision: rev }) => ({ plan_id, version, revision: rev })),
    },
  ),
  commit: (id: string, op: string, warnings: string[], key: string) => write<ActionReceipt>(
    `/trips/${encodeURIComponent(id)}/operations/commit`, 'POST',
    { operation_id: op, confirmed: true, acknowledged_issue_ids: warnings }, key,
  ),
  expenseReport: (params = new URLSearchParams(), signal?: AbortSignal) => call<ExpenseReport>(`/expenses/summary?${params}`, { signal }),
  expensePreview: (entry: ExpenseLine, planId: string | null) => write<ExpenseAssignment>(
    `/expenses/${encodeURIComponent(entry.entry_ref)}/assignment/preview`, 'POST',
    { plan_id: planId, expected_entry_revision: entry.revision },
  ),
  expenseCommit: (entry: ExpenseLine, operation: string, key: string) => write<{ entry_ref: string; trip_plan_id: string | null }>(
    `/expenses/${encodeURIComponent(entry.entry_ref)}/assignment/commit`, 'POST', {operation_id: operation, confirmed: true}, key,
  ),
  preferences: (signal?: AbortSignal) => call<PreferencesView>('/preferences', { signal }),
  editPreference: (field: string, value: string | { amount: string; currency: string } | null, use: boolean, revision: string) => write<PreferencesView>(
    `/preferences/${encodeURIComponent(field)}`, 'PUT', { expected_revision: revision, value, use_for_planning: use },
  ),
  setting: (enabled: boolean, revision: string) => write<PreferencesView>('/preferences/settings', 'PUT', { enabled, expected_revision: revision }),
  favorites: (offset = 0, signal?: AbortSignal) => call<{ items: Favorite[]; next_offset: number | null }>(`/favorites?offset=${offset}`, { signal }),
  saveFavorite: (kind: FavoriteKind, ref: PlanRef, optionId?: string, direction?: 'outbound' | 'inbound') => write<Favorite>(
    '/favorites', 'POST', { kind, ref, option_id: optionId, direction },
  ),
  dropFavorite: (id: string) => write<{ removed: boolean }>(`/favorites/${encodeURIComponent(id)}`, 'DELETE', undefined),
}
