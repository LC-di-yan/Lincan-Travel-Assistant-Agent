// ===== SSE 事件类型 =====

export interface SSEEvent {
  event: 'thinking' | 'intention' | 'dispatching' | 'agent_result' | 'complete' | 'error'
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
