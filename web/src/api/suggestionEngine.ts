import type { IntentionData, AgentResult, KeyEntities } from './types'

// ── 类型定义 ──────────────────────────────────────────

export interface FollowUpSuggestion {
  id: string
  text: string
  query: string
  type: 'deepen' | 'explore' | 'action' | 'fallback'
  source: 'rule' | 'llm'
  icon: string
}

export interface UserPersona {
  homeCity?: string
  frequentDestinations?: string[]
  preferences?: { type: string; value: string }[]
  recentTrips?: { destination: string; date: string }[]
  totalExpenses?: number
}

export interface SuggestionContext {
  userMessage: string
  intention: IntentionData | null
  agentResults: AgentResult[]
  persona: UserPersona
}

interface RuleTemplate {
  id: string
  type: FollowUpSuggestion['type']
  icon: string
  text: string
  query: string
  baseWeight: number
  condition: (ctx: RuleEvalContext) => boolean
}

interface RuleEvalContext {
  entities: KeyEntities
  inner: Record<string, unknown>
  extras: Record<string, unknown>
  answerText: string
}

interface ClickStats {
  [templateId: string]: {
    clicks: number
    impressions: number
    lastClicked: number
  }
}

// ── 数据提取 ──────────────────────────────────────────

function getInner(result: AgentResult): Record<string, unknown> {
  const d = result.data as Record<string, unknown>
  return (d.data as Record<string, unknown>) || d
}

function getAnswerText(inner: Record<string, unknown>): string {
  return (inner.answer || inner.content || inner.result || inner.summary || inner.message || '') as string
}

/** 从 intention + agentResults 中提取所有可用实体 */
function extractExtras(intention: IntentionData | null, results: AgentResult[]): Record<string, unknown> {
  const extras: Record<string, unknown> = {}
  const entities = intention?.key_entities

  if (entities?.destination) extras.destination = entities.destination
  if (entities?.origin) extras.origin = entities.origin
  if (entities?.date) extras.date = entities.date
  if (entities?.duration) extras.duration = entities.duration
  // other 字段有时包含城市名
  if (entities?.other && !extras.destination) extras.destination = entities.other

  for (const r of results) {
    const inner = getInner(r)
    switch (r.agent_name) {
      case 'expense_tracker':
      case 'expense_tracking': {
        const exp = inner.expense as Record<string, unknown> | undefined
        if (exp) {
          if (exp.category) extras.expense_category = exp.category
          if (exp.amount != null) extras.expense_amount = exp.amount
          if (exp.description) extras.expense_description = exp.description
        }
        if (inner.total_after != null) extras.total_after = inner.total_after
        if (inner.summary) {
          const s = inner.summary as Record<string, unknown>
          if (s.total != null) extras.expense_total = s.total
        }
        break
      }
      case 'currency_converter':
      case 'currency_conversion': {
        if (inner.from_currency) extras.from_currency = inner.from_currency
        if (inner.to_currency) extras.to_currency = inner.to_currency
        if (inner.from_amount) extras.from_amount = inner.from_amount
        if (inner.to_amount) extras.to_amount = inner.to_amount
        if (inner.from) extras.from_currency = inner.from
        if (inner.to) extras.to_currency = inner.to
        if (inner.amount) extras.from_amount = inner.amount
        if (inner.result) extras.to_amount = inner.result
        if (inner.rate) extras.rate = inner.rate
        break
      }
      case 'preference': {
        const prefs = inner.preferences as Record<string, unknown> | undefined
        const prefList = (prefs?.preferences || prefs) as { type: string; value: string }[] | undefined
        if (Array.isArray(prefList) && prefList.length > 0) {
          extras.pref_types = prefList.map((p) => p.type)
          extras.pref_first_type = prefList[0].type
          extras.pref_first_value = prefList[0].value
          // 从偏好值中提取城市名
          const prefValue = String(prefList[0].value || '')
          const city = extractCityName(prefValue)
          if (city && !extras.destination) {
            extras.destination = city
          }
        }
        break
      }
      case 'itinerary_planning': {
        const itin = (inner.itinerary || inner) as Record<string, unknown> | undefined
        if (itin?.title) extras.itinerary_title = itin.title
        break
      }
      case 'event_collection': {
        if (inner.destination) extras.destination = extras.destination || inner.destination
        if (inner.date) extras.date = extras.date || inner.date
        if (inner.start_date) extras.date = extras.date || inner.start_date
        break
      }
      case 'information_query': {
        if (inner.query_type) extras.query_type = inner.query_type
        if (inner.summary) extras.info_summary = inner.summary
        // 天气查询结果常有 city / location 字段
        const city = (inner.city || inner.location || inner.city_name) as string
        if (city && !extras.destination) extras.destination = city
        break
      }
      case 'train_ticket': {
        if (inner.train_count != null) extras.train_count = inner.train_count
        if (inner.fastest_train) extras.fastest_train = inner.fastest_train
        if (inner.count != null) extras.train_count = inner.count
        break
      }
      case 'translation': {
        if (inner.source_lang) extras.source_lang = inner.source_lang
        if (inner.target_lang) extras.target_lang = inner.target_lang
        if (inner.source_text) extras.source_text = inner.source_text
        break
      }
    }
  }

  return extras
}

// ── 模板填充 ──────────────────────────────────────────

function fill(template: string, entities: KeyEntities, extras: Record<string, unknown>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    if (key in extras && extras[key] != null) return String(extras[key])
    const ek = key as keyof KeyEntities
    if (ek in entities && entities[ek] != null) return String(entities[ek])
    return ''
  })
}

// ── 条件辅助 ──────────────────────────────────────────

function always(): boolean { return true }

function hasExtra(extras: Record<string, unknown>, key: string): boolean {
  const v = extras[key]
  return v != null && v !== ''
}

function hasEntity(entities: KeyEntities, key: keyof KeyEntities): boolean {
  const v = entities[key]
  return v != null && v !== ''
}

function numGt(extras: Record<string, unknown>, key: string, threshold: number): boolean {
  const v = extras[key]
  return typeof v === 'number' && v > threshold
}

function numLte(extras: Record<string, unknown>, key: string, threshold: number): boolean {
  const v = extras[key]
  return typeof v === 'number' && v <= threshold
}

function hasKeyword(text: string, keywords: string[]): boolean {
  return keywords.some((kw) => text.includes(kw))
}

function matchPrefType(extras: Record<string, unknown>, type: string): boolean {
  const types = extras.pref_types as string[] | undefined
  if (!types?.length) return false
  if (types.includes(type)) return true
  const aliases: Record<string, string[]> = {
    'destination': ['travel', 'city', 'destination', 'trip', 'place', 'travel_city', 'favorite_city'],
    'hotel': ['hotel', 'hotel_brand', 'accommodation', 'lodging'],
    'transport': ['transport', 'transit', 'car', 'flight', 'train', 'travel_mode'],
    'food': ['food', 'diet', 'meal', 'cuisine'],
    'airline': ['airline', 'flight', 'seat', 'air'],
  }
  return aliases[type]?.some(a => types.includes(a)) ?? false
}

// ── 城市名提取 ──────────────────────────────────────────

const CITY_LIST = [
  '北京', '上海', '广州', '深圳', '杭州', '南京', '成都', '武汉', '西安', '重庆',
  '青岛', '厦门', '大连', '天津', '苏州', '长沙', '郑州', '济南', '合肥', '福州',
  '南昌', '昆明', '贵阳', '南宁', '海口', '三亚', '拉萨', '乌鲁木齐', '哈尔滨',
  '长春', '沈阳', '太原', '石家庄', '兰州', '西宁', '银川', '呼和浩特', '桂林',
  '珠海', '东莞', '佛山', '无锡', '宁波', '温州', '常州', '烟台', '威海', '洛阳',
  '北海', '丽江', '大理', '西双版纳', '张家界', '黄山', '秦皇岛', '延边',
]

function extractCityName(text: string): string | null {
  if (!text) return null
  for (const city of CITY_LIST) {
    if (text.includes(city)) return city
  }
  const m = text.match(/去([一-龥]{2,4})(?:出差|旅游|玩|吧|啊|呢|$)/)
  if (m) return m[1]
  return null
}

// ── 规则模板库 ────────────────────────────────────────

const RULE_GROUPS: Record<string, RuleTemplate[]> = {
  expense_tracking: [
    { id: 'exp_deepen_summary', type: 'deepen', icon: '📊', text: '查看费用汇总', query: '查看我的差旅费用汇总', baseWeight: 110, condition: always },
    { id: 'exp_deepen_export', type: 'deepen', icon: '📋', text: '导出报销单', query: '帮我导出费用明细用于报销', baseWeight: 105, condition: always },
    { id: 'exp_explore_materials', type: 'explore', icon: '📝', text: '报销材料清单', query: '差旅报销需要准备哪些材料', baseWeight: 95, condition: always },
    { id: 'exp_explore_hotel', type: 'explore', icon: '🏨', text: '{destination}住宿标准', query: '{destination}出差住宿标准是多少', baseWeight: 90, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'exp_explore_meal', type: 'explore', icon: '🍽️', text: '{destination}餐补标准', query: '{destination}出差餐补标准', baseWeight: 85, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'exp_explore_budget', type: 'explore', icon: '💰', text: '预算还剩多少', query: '这个月差旅预算还剩多少', baseWeight: 80, condition: (c) => numGt(c.extras, 'expense_amount', 500) || numGt(c.extras, 'expense_total', 500) },
    { id: 'exp_action_add', type: 'action', icon: '➕', text: '再记一笔', query: '记一笔午餐费', baseWeight: 60, condition: always },
  ],
  expense_tracker: [], // alias, filled below

  currency_conversion: [
    { id: 'cur_deepen_reverse', type: 'deepen', icon: '🔄', text: '反向汇率', query: '1 {to_currency}等于多少{from_currency}', baseWeight: 110, condition: always },
    { id: 'cur_explore_eur', type: 'explore', icon: '💱', text: '欧元汇率', query: '{from_currency}兑欧元汇率', baseWeight: 95, condition: (c) => hasExtra(c.extras, 'from_currency') },
    { id: 'cur_explore_jpy', type: 'explore', icon: '💴', text: '日元汇率', query: '{from_currency}兑日元汇率', baseWeight: 90, condition: (c) => hasExtra(c.extras, 'from_currency') },
    { id: 'cur_deepen_bigger', type: 'deepen', icon: '💰', text: '更大金额', query: '{from_amount_x10} {from_currency}等于多少{to_currency}', baseWeight: 100, condition: (c) => numLte(c.extras, 'from_amount', 1000) && hasExtra(c.extras, 'from_amount') },
    { id: 'cur_explore_overseas', type: 'explore', icon: '💳', text: '境外消费报销', query: '境外消费怎么报销', baseWeight: 85, condition: always },
    { id: 'cur_action_history', type: 'action', icon: '📊', text: '查看历史汇率', query: '最近美元汇率走势', baseWeight: 60, condition: always },
  ],
  currency_converter: [], // alias

  preference: [
    // 跨技能衔接（权重 108-120，优先于偏好管理类）
    { id: 'pref_cross_plan', type: 'deepen', icon: '🧳', text: '规划去{destination}的行程', query: '帮我规划去{destination}的出差行程', baseWeight: 120, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'pref_cross_train', type: 'deepen', icon: '🚂', text: '怎么去{destination}', query: '查一下去{destination}的火车票', baseWeight: 118, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'pref_cross_weather', type: 'explore', icon: '🌤️', text: '{destination}天气', query: '{destination}天气怎么样', baseWeight: 115, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'pref_cross_hotel', type: 'explore', icon: '🏨', text: '{destination}住宿价格', query: '去{destination}住酒店大概要多少钱', baseWeight: 112, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'pref_cross_standard', type: 'explore', icon: '💰', text: '{destination}住宿标准', query: '{destination}出差住宿标准是多少', baseWeight: 108, condition: (c) => hasExtra(c.extras, 'destination') },
    // 偏好管理类（权重 55-110）
    { id: 'pref_deepen_view', type: 'deepen', icon: '📋', text: '查看我的偏好', query: '我有哪些偏好设置', baseWeight: 110, condition: always },
    { id: 'pref_deepen_hotel', type: 'deepen', icon: '🏨', text: '其他酒店品牌', query: '我还喜欢全季酒店', baseWeight: 100, condition: (c) => matchPrefType(c.extras, 'hotel') || matchPrefType(c.extras, 'hotel_brand') },
    { id: 'pref_deepen_room', type: 'deepen', icon: '🛏️', text: '房型偏好', query: '我喜欢大床房', baseWeight: 95, condition: (c) => matchPrefType(c.extras, 'hotel') },
    { id: 'pref_explore_seat', type: 'explore', icon: '🧳', text: '座位偏好', query: '我偏好靠过道座位', baseWeight: 85, condition: (c) => matchPrefType(c.extras, 'airline') },
    { id: 'pref_explore_food', type: 'explore', icon: '🥡', text: '饮食禁忌', query: '我有饮食禁忌需要备注', baseWeight: 85, condition: (c) => matchPrefType(c.extras, 'food') },
    { id: 'pref_explore_transport', type: 'explore', icon: '🚕', text: '出行偏好', query: '我偏好打车出行', baseWeight: 80, condition: always },
    { id: 'pref_action_delete', type: 'action', icon: '❌', text: '删除偏好', query: '帮我删除一个偏好', baseWeight: 55, condition: always },
  ],

  itinerary_planning: [
    { id: 'itin_deepen_weather', type: 'deepen', icon: '🌤️', text: '{destination}天气', query: '{destination}天气怎么样', baseWeight: 115, condition: (c) => hasEntity(c.entities, 'destination') || hasExtra(c.extras, 'destination') },
    { id: 'itin_deepen_return', type: 'deepen', icon: '🚂', text: '回程车票', query: '查询从{destination}回{origin}的火车票', baseWeight: 110, condition: (c) => hasEntity(c.entities, 'origin') && (hasEntity(c.entities, 'destination') || hasExtra(c.extras, 'destination')) },
    { id: 'itin_deepen_hotel', type: 'deepen', icon: '🏨', text: '{destination}酒店', query: '{destination}有什么推荐酒店', baseWeight: 105, condition: (c) => hasEntity(c.entities, 'destination') || hasExtra(c.extras, 'destination') },
    { id: 'itin_explore_notes', type: 'explore', icon: '📝', text: '注意事项', query: '去{destination}出差有什么注意事项', baseWeight: 95, condition: (c) => hasEntity(c.entities, 'destination') || hasExtra(c.extras, 'destination') },
    { id: 'itin_explore_food', type: 'explore', icon: '🍜', text: '美食推荐', query: '{destination}有什么好吃的', baseWeight: 90, condition: (c) => hasEntity(c.entities, 'destination') || hasExtra(c.extras, 'destination') },
    { id: 'itin_explore_emergency', type: 'explore', icon: '🏥', text: '应急信息', query: '{destination}医院和紧急联系方式', baseWeight: 85, condition: (c) => hasEntity(c.entities, 'destination') || hasExtra(c.extras, 'destination') },
    { id: 'itin_explore_weekend', type: 'explore', icon: '🗺️', text: '周末去哪', query: '{destination}周末周边游玩推荐', baseWeight: 80, condition: (c) => numGt(c.extras, 'duration', 2) || (hasEntity(c.entities, 'duration') && Number(c.entities.duration) >= 3) },
    { id: 'itin_deepen_detail', type: 'deepen', icon: '📅', text: '每日详情', query: '帮我看看每天的详细安排', baseWeight: 100, condition: always },
    { id: 'itin_action_budget', type: 'action', icon: '💰', text: '预估总费用', query: '这次出差大概需要多少预算', baseWeight: 65, condition: always },
    { id: 'itin_action_export', type: 'action', icon: '📤', text: '导出行程', query: '把行程导出为 PDF', baseWeight: 55, condition: always },
  ],
  event_collection: [], // shares with itinerary_planning

  information_query: [
    { id: 'info_deepen_forecast', type: 'deepen', icon: '📅', text: '未来几天天气', query: '{destination}未来三天天气', baseWeight: 110, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'info_explore_train', type: 'explore', icon: '🚂', text: '去{destination}车票', query: '查去{destination}的火车票', baseWeight: 95, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'info_explore_clothes', type: 'explore', icon: '🧥', text: '穿衣建议', query: '{destination}现在穿什么衣服合适', baseWeight: 90, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'info_deepen_more', type: 'deepen', icon: '🔍', text: '更详细信息', query: '帮我查更详细的{destination}信息', baseWeight: 100, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'info_explore_hotel', type: 'explore', icon: '🏨', text: '住宿推荐', query: '{destination}住宿推荐', baseWeight: 85, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'info_explore_news', type: 'explore', icon: '📰', text: '最新动态', query: '{destination}最近有什么新闻', baseWeight: 75, condition: (c) => hasExtra(c.extras, 'destination') },
    // 无 destination 也能用的通用追问
    { id: 'info_deepen_other_city', type: 'deepen', icon: '🌤️', text: '查其他城市天气', query: '上海天气怎么样', baseWeight: 95, condition: always },
    { id: 'info_explore_train_any', type: 'explore', icon: '🚂', text: '查火车票', query: '帮我查火车票', baseWeight: 85, condition: always },
    { id: 'info_action_plan', type: 'action', icon: '🧳', text: '规划行程', query: '帮我规划一个出差行程', baseWeight: 65, condition: always },
  ],

  rag_knowledge: [
    { id: 'rag_deepen_standard', type: 'deepen', icon: '🏨', text: '不同城市标准', query: '不同城市的住宿标准一样吗', baseWeight: 110, condition: (c) => hasKeyword(c.answerText, ['住宿', '标准', '酒店']) },
    { id: 'rag_deepen_process', type: 'deepen', icon: '📄', text: '报销流程', query: '差旅报销的具体流程', baseWeight: 110, condition: (c) => hasKeyword(c.answerText, ['报销', '费用']) },
    { id: 'rag_deepen_meal', type: 'deepen', icon: '🍽️', text: '餐补详情', query: '餐补按什么标准发放', baseWeight: 105, condition: (c) => hasKeyword(c.answerText, ['餐补', '餐饮', '餐费']) },
    { id: 'rag_deepen_transport', type: 'deepen', icon: '🚕', text: '交通报销上限', query: '打车报销有上限吗', baseWeight: 105, condition: (c) => hasKeyword(c.answerText, ['交通', '打车', '出行']) },
    { id: 'rag_explore_full', type: 'explore', icon: '📋', text: '查看全部政策', query: '差旅政策完整版', baseWeight: 90, condition: always },
    { id: 'rag_explore_faq', type: 'explore', icon: '❓', text: '常见问题', query: '差旅报销常见问题', baseWeight: 85, condition: always },
    { id: 'rag_explore_emergency', type: 'explore', icon: '🆘', text: '紧急联系', query: '出差遇到紧急情况联系谁', baseWeight: 80, condition: always },
  ],

  train_ticket: [
    { id: 'train_deepen_more', type: 'deepen', icon: '🚂', text: '其他车次', query: '还有哪些车次可以选择', baseWeight: 110, condition: always },
    { id: 'train_deepen_seat', type: 'deepen', icon: '💺', text: '座位类型价格', query: '一等座和二等座差多少钱', baseWeight: 105, condition: always },
    { id: 'train_explore_hotel', type: 'explore', icon: '🏨', text: '{destination}住宿', query: '{destination}酒店推荐', baseWeight: 90, condition: (c) => hasExtra(c.extras, 'destination') },
    { id: 'train_explore_other', type: 'explore', icon: '🚌', text: '其他交通方式', query: '有没有高铁以外的选择', baseWeight: 85, condition: always },
    { id: 'train_action_buy', type: 'action', icon: '🎫', text: '购票流程', query: '12306怎么在线购票', baseWeight: 60, condition: always },
  ],

  translation: [
    { id: 'trans_deepen_reverse', type: 'deepen', icon: '🔄', text: '反向翻译', query: '帮我把刚才的译文翻译回{source_lang}', baseWeight: 110, condition: (c) => hasExtra(c.extras, 'source_lang') },
    { id: 'trans_explore_more', type: 'explore', icon: '📝', text: '翻译更多', query: '再帮我翻译一段', baseWeight: 95, condition: always },
    { id: 'trans_explore_phrases', type: 'explore', icon: '🗣️', text: '常用语', query: '{target_lang}常用旅行短语', baseWeight: 90, condition: (c) => hasExtra(c.extras, 'target_lang') },
    { id: 'trans_explore_jp', type: 'explore', icon: '🇯🇵', text: '翻译成日语', query: '翻译成日语', baseWeight: 85, condition: always },
  ],

  memory_query: [
    { id: 'mem_deepen_more', type: 'deepen', icon: '📋', text: '更多历史', query: '我还有哪些出行记录', baseWeight: 110, condition: always },
    { id: 'mem_explore_stats', type: 'explore', icon: '📊', text: '出行统计', query: '我的出行统计', baseWeight: 95, condition: always },
    { id: 'mem_explore_top', type: 'explore', icon: '⭐', text: '最常去城市', query: '我去过最多次的城市是哪个', baseWeight: 90, condition: always },
    { id: 'mem_action_plan', type: 'action', icon: '🧳', text: '规划新行程', query: '帮我规划一个新行程', baseWeight: 60, condition: always },
  ],
}

// Fill aliases (same rules for both name variants)
RULE_GROUPS.expense_tracker = RULE_GROUPS.expense_tracking
RULE_GROUPS.currency_converter = RULE_GROUPS.currency_conversion
RULE_GROUPS.event_collection = RULE_GROUPS.itinerary_planning

// ── 兜底规则 ──────────────────────────────────────────

interface FallbackRule {
  id: string
  icon: string
  text: string
  query: string
  condition: (persona: UserPersona) => boolean
}

const FALLBACK_RULES: FallbackRule[] = [
  { id: 'fall_from_home', icon: '🧳', text: '从{home}出发', query: '从{home}出发去出差', condition: (p) => !!p.homeCity },
  { id: 'fall_revisit', icon: '🔁', text: '再去{recent}', query: '再去{recent}出差', condition: (p) => !!p.recentTrips?.length },
  { id: 'fall_expense', icon: '📊', text: '查看费用汇总', query: '查看我的差旅费用汇总', condition: always },
  { id: 'fall_weather', icon: '🌤️', text: '查天气', query: '北京天气怎么样', condition: always },
  { id: 'fall_currency', icon: '💱', text: '汇率查询', query: '100美元等于多少人民币', condition: always },
  { id: 'fall_help', icon: '💡', text: '能做什么', query: '你能帮我做什么', condition: always },
]

// ── localStorage 点击统计 ─────────────────────────────

const STATS_KEY = 'aligo_suggestion_stats'

function loadStats(): ClickStats {
  try {
    const raw = localStorage.getItem(STATS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveStats(stats: ClickStats): void {
  try { localStorage.setItem(STATS_KEY, JSON.stringify(stats)) } catch { /* ignore */ }
}

function getClickBoost(templateId: string): number {
  const stats = loadStats()
  const s = stats[templateId]
  if (!s || s.impressions < 3) return 0
  const ctr = s.clicks / s.impressions
  if (ctr > 0.5) return 30
  if (ctr > 0.3) return 20
  if (ctr > 0.15) return 10
  if (s.impressions >= 10 && ctr === 0) return -20
  return 0
}

// ── 记录展示 ──────────────────────────────────────────

export function recordImpression(templateId: string): void {
  const stats = loadStats()
  const s = stats[templateId] || { clicks: 0, impressions: 0, lastClicked: 0 }
  s.impressions++
  stats[templateId] = s
  saveStats(stats)
}

export function recordClick(templateId: string): void {
  const stats = loadStats()
  const s = stats[templateId] || { clicks: 0, impressions: 0, lastClicked: 0 }
  s.clicks++
  s.lastClicked = Date.now()
  stats[templateId] = s
  saveStats(stats)
}

// ── 主生成函数 ────────────────────────────────────────

export function generateSuggestions(ctx: SuggestionContext): FollowUpSuggestion[] {
  const entities = ctx.intention?.key_entities || {}
  const extras = extractExtras(ctx.intention, ctx.agentResults)

  // 从用户消息中提取城市名（城市列表匹配 + 正则兜底）
  if (!extras.destination) {
    extras.destination = extractCityName(ctx.userMessage)
  }

  // 收集所有候选
  interface Candidate {
    id: string
    type: FollowUpSuggestion['type']
    icon: string
    text: string
    query: string
    weight: number
  }

  const candidates: Candidate[] = []

  for (const result of ctx.agentResults) {
    const rules = RULE_GROUPS[result.agent_name]
    if (!rules || rules.length === 0) continue

    const inner = getInner(result)
    const answerText = getAnswerText(inner)
    const evalCtx: RuleEvalContext = { entities, inner, extras, answerText }

    for (const rule of rules) {
      if (!rule.condition(evalCtx)) continue

      const text = fill(rule.text, entities, extras)
      const query = fill(rule.query, entities, extras)

      // 跳过填充不完整的模板
      if (!query.trim() || query.includes('{')) continue

      const boost = getClickBoost(rule.id)
      candidates.push({
        id: rule.id,
        type: rule.type,
        icon: rule.icon,
        text,
        query,
        weight: rule.baseWeight + boost,
      })
    }
  }

  // 去重（同 query 只保留最高权重）
  const seen = new Map<string, Candidate>()
  for (const c of candidates) {
    const existing = seen.get(c.query)
    if (!existing || c.weight > existing.weight) {
      seen.set(c.query, c)
    }
  }

  let unique = [...seen.values()]

  // 额外处理：若 from_amount 可用、有 bigger 金额模板，修正数值
  for (const c of unique) {
    if (c.id === 'cur_deepen_bigger' && extras.from_amount) {
      const amt = Number(extras.from_amount)
      if (!isNaN(amt)) {
        c.text = c.text.replace('{from_amount_x10}', String(amt * 10))
        c.query = c.query.replace('{from_amount_x10}', String(amt * 10))
      }
    }
  }

  // 兜底
  if (unique.length === 0) {
    const fb = buildFallbacks(ctx.persona)
    unique = fb.map((f) => ({
      id: f.id,
      type: 'fallback' as FollowUpSuggestion['type'],
      icon: f.icon,
      text: f.text,
      query: f.query,
      weight: 50,
    }))
  }

  // 排序：类型优先 > 权重
  const typeOrder: Record<string, number> = { deepen: 0, explore: 1, action: 2, fallback: 3 }
  unique.sort((a, b) => {
    const td = typeOrder[a.type] - typeOrder[b.type]
    if (td !== 0) return td
    return b.weight - a.weight
  })

  // 类型配比：最多 2 深化 + 2 扩展，不足用 action/fallback 补齐
  const deepens = unique.filter((s) => s.type === 'deepen')
  const explores = unique.filter((s) => s.type === 'explore')
  const others = unique.filter((s) => s.type === 'action' || s.type === 'fallback')

  const selected: Candidate[] = []
  selected.push(...deepens.slice(0, 2))
  selected.push(...explores.slice(0, 2))
  for (const o of others) {
    if (selected.length >= 4) break
    selected.push(o)
  }

  return selected.slice(0, 4).map((c) => ({
    id: c.id,
    text: c.icon ? `${c.icon} ${c.text}` : c.text,
    query: c.query,
    type: c.type,
    source: 'rule',
    icon: c.icon,
  }))
}

function buildFallbacks(persona: UserPersona): FallbackRule[] {
  const result: FallbackRule[] = []
  for (const rule of FALLBACK_RULES) {
    if (rule.condition(persona)) {
      let text = rule.text
      let query = rule.query
      if (rule.id === 'fall_from_home' && persona.homeCity) {
        text = text.replace('{home}', persona.homeCity)
        query = query.replace('{home}', persona.homeCity)
      }
      if (rule.id === 'fall_revisit' && persona.recentTrips?.length) {
        const dest = persona.recentTrips[0].destination
        text = text.replace('{recent}', dest)
        query = query.replace('{recent}', dest)
      }
      result.push({ ...rule, text, query })
    }
  }
  if (result.length === 0) {
    // 无条件兜底
    return FALLBACK_RULES.filter((r) => r.id === 'fall_expense' || r.id === 'fall_weather' || r.id === 'fall_currency' || r.id === 'fall_help')
  }
  return result
}
