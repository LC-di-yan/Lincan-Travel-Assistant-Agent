import type { TurnActivity } from '../utils/agentActivity'
import type { ConflictReport, PlanLink, PlanRef } from './personal'

// ===== SSE 事件类型 =====

export interface SSEEvent {
  event: 'thinking' | 'intention' | 'dispatching' | 'agent_start' | 'agent_result' | 'complete' | 'error' | 'clarification'
  data: string
}

// ===== 意图识别 =====

export interface Intent {
  type: string
  confidence: number
  description: string
  reason: string
}

export interface KeyEntities {
  origin?: string | null
  destination?: string | null
  date?: string | null
  duration?: string | null
  other?: string | null
}

export interface AgentSchedule {
  agent_name: string
  priority: number
  reason: string
  expected_output: string
  node_id?: string
  label?: string
  depends_on?: string[]
}

export type PublicAgent = Pick<AgentSchedule, 'agent_name' | 'node_id' | 'label' | 'depends_on'>

export interface IntentionData {
  reasoning: string
  intents: Intent[]
  key_entities: KeyEntities
  rewritten_query: string
  needs_clarification?: boolean
  clarification_question?: string
  fast_event?: {
    origin?: string | null
    destination?: string | null
    start_date?: string | null
    end_date?: string | null
    duration_days?: number | null
    trip_purpose?: string | null
    missing_info?: string[]
  }
  agent_schedule: AgentSchedule[]
  trip_request?: Record<string, unknown>
}

// ===== Agent 结果 =====

export interface AgentResult {
  agent_name: string
  priority: number
  status: 'success' | 'error'
  data: Record<string, unknown>
  node_id?: string
  label?: string
  node_status?: 'running' | 'success' | 'partial' | 'failed' | 'unavailable' | 'timeout' | 'skipped' | 'cancelled'
  cached?: boolean
}

export interface OrchestrationResult {
  answer?: string
  status: string
  history_warning?: string
  intention?: IntentionData
  agents_executed: number
  results: AgentResult[]
  errors?: number
  trip_plan?: Record<string, unknown>
  selected_proposal?: string
  candidate_ref?: string
  candidate_session_id?: string
  candidate_base?: PlanRef
  candidate_base_revision?: number
  personal_conflicts?: ConflictReport
}

// ===== 行程规划 =====

export interface Activity {
  time: string
  activity: string
  /** 活动地点，模型可能返回；活动名缺失时可作兜底 */
  location?: string
  description: string
  transport?: string
}

export interface DailyPlan {
  day: string | number
  date?: string
  city?: string
  theme?: string
  activities: Activity[]
  meals?: { lunch?: string; dinner?: string }
}

export interface Itinerary {
  title: string
  duration: string
  route?: string
  daily_plans: DailyPlan[]
  notes?: string[]
  estimated_budget?: string
  price_notice?: string
  sources?: { title?: string; url?: string }[]
  planning_complete?: boolean
}

// ===== 偏好 =====

export interface Preference {
  type: string
  value: string | string[]
  action?: 'append' | 'replace'
}

// ===== 历史行程 =====

export interface TripRecord {
  trip_id: string
  timestamp: string
  origin: string
  destination: string
  start_date: string
  end_date: string
  purpose: string
}

export interface FrequentDestination {
  city: string
  count: number
}

// ===== 酒店搜索 =====

export interface HotelItem {
  id: string
  name: string
  address: string
  rating: string
  cost: string
  tel: string
  photo: string
  distance: string
  type: string
  location: string
}

export interface HotelResultData {
  city: string
  keyword: string
  count: number
  summary: string
  hotels: HotelItem[]
  sources: { title: string; url: string }[]
}

// ===== 餐厅搜索 =====

export interface RestaurantItem {
  id: string
  name: string
  address: string
  rating: string
  cost: string
  tel: string
  photo: string
  distance: string
  type: string
  location: string
}

export interface RestaurantResultData {
  city: string
  keyword: string
  count: number
  summary: string
  restaurants: RestaurantItem[]
  sources: { title: string; url: string }[]
}

// ===== 景点搜索 =====

export interface ScenicItem {
  id: string
  name: string
  address: string
  rating: string
  cost: string
  tel: string
  photo: string
  distance: string
  type: string
  location: string
}

export interface ScenicResultData {
  city: string
  keyword: string
  count: number
  summary: string
  attractions: ScenicItem[]
  sources: { title: string; url: string }[]
}

// ===== 消息 =====

export interface Message {
  requestId?: string
  planLink?: PlanLink
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  confirmedOptionId?: string
  selectionReceipt?: { sourceMessageId: string; optionId: string; number: number }
  activity?: TurnActivity
  historical?: boolean
  historyWarning?: string
  startedAt?: number
  intention?: IntentionData
  agentResults?: AgentResult[]
  orchestrationResult?: OrchestrationResult
  narrationText?: string  // LLM 生成的播报文案（手动播放优先用）
  /** 显式错误标记。
   *  此前错误态靠 content.startsWith('❌') 判断——emoji 承载状态语义，
   *  既违反无 emoji 图标规范，也会在文案改动时静默失效。 */
  isError?: boolean
}
