// ===== SSE 事件类型 =====

export interface SSEEvent {
  event: 'thinking' | 'intention' | 'dispatching' | 'agent_result' | 'complete' | 'error' | 'clarification'
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
}

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
}

// ===== Agent 结果 =====

export interface AgentResult {
  agent_name: string
  priority: number
  status: 'success' | 'error'
  data: Record<string, unknown>
}

export interface OrchestrationResult {
  status: string
  intention?: IntentionData
  agents_executed: number
  results: AgentResult[]
  errors?: number
}

// ===== 行程规划 =====

export interface Activity {
  time: string
  activity: string
  description: string
  transport?: string
}

export interface DailyPlan {
  day: string
  activities: Activity[]
  meals?: { lunch?: string; dinner?: string }
}

export interface Itinerary {
  title: string
  duration: string
  daily_plans: DailyPlan[]
  notes?: string[]
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

// ===== 消息 =====

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  startedAt?: number
  intention?: IntentionData
  agentResults?: AgentResult[]
  orchestrationResult?: OrchestrationResult
}
