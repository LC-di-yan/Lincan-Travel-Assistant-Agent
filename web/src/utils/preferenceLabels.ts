export type PreferenceGroup = 'travel' | 'stay' | 'life' | 'other'

const PREFERENCE_DETAILS: Record<string, { label: string; group: PreferenceGroup }> = {
  hotel_brand: { label: '酒店品牌', group: 'stay' },
  hotel_brands: { label: '酒店品牌', group: 'stay' },
  hotel: { label: '酒店偏好', group: 'stay' },
  airline: { label: '航空公司', group: 'stay' },
  airlines: { label: '航空公司', group: 'stay' },
  seat: { label: '座位偏好', group: 'stay' },
  seat_preference: { label: '座位偏好', group: 'stay' },
  food: { label: '餐饮偏好', group: 'life' },
  food_preference: { label: '美食偏好', group: 'life' },
  meal_preference: { label: '餐食偏好', group: 'life' },
  dietary: { label: '饮食偏好', group: 'life' },
  dietary_preference: { label: '饮食偏好', group: 'life' },
  transport: { label: '出行方式', group: 'stay' },
  transportation_preference: { label: '交通偏好', group: 'stay' },
  transport_preference: { label: '交通偏好', group: 'stay' },
  home: { label: '常住城市', group: 'travel' },
  home_location: { label: '常驻地', group: 'travel' },
  city: { label: '偏好城市', group: 'travel' },
  favorite_city: { label: '心仪城市', group: 'travel' },
  budget: { label: '预算偏好', group: 'life' },
  budget_level: { label: '预算等级', group: 'life' },
  travel_preference: { label: '旅行方式', group: 'travel' },
  weather_preference: { label: '天气偏好', group: 'travel' },
  trip_style: { label: '旅行风格', group: 'travel' },
}

/** 结果卡片与已保存偏好侧栏共用，不把未知内部英文键直接展示给用户。 */
export function preferenceLabel(type: string | undefined): string {
  const key = type?.trim() || ''
  return PREFERENCE_DETAILS[key]?.label || (/\p{Script=Han}/u.test(key) && !/[a-z_]/i.test(key) ? key : '其他偏好')
}

export function preferenceGroup(type: string): PreferenceGroup {
  return PREFERENCE_DETAILS[type]?.group || 'other'
}
