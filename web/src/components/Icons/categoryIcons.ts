import {
  Armchair,
  Briefcase,
  Building2,
  Car,
  Clapperboard,
  CloudSun,
  Heart,
  Hotel,
  House,
  Luggage,
  Package,
  Pin,
  Plane,
  Smartphone,
  Sparkles,
  Utensils,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

/**
 * 分类图标映射（共享，纯数据模块）
 *
 * 取代此前散落在 PreferenceCard / PreferencePanel / ExpenseCard / ExpensePanel 的
 * emoji 映射表，其中两处费用分类表完全重复。改用 lucide SVG 后：
 * - 与既有图标体系一致（Header / InputBar / RouteStrip 已用 lucide）
 * - 继承 currentColor，自动适配明暗主题与语义色
 * - 描边统一 1.5，尺寸由调用方给，避免 emoji 跨系统字形不一致
 *
 * 组件与本表分文件：react-refresh 要求组件文件只导出组件，否则热更新失效。
 */

export const PREFERENCE_ICONS: Record<string, LucideIcon> = {
  hotel_brand: Hotel,
  hotel_brands: Hotel,
  hotel: Hotel,
  airline: Plane,
  airlines: Plane,
  seat: Armchair,
  seat_preference: Armchair,
  food: Utensils,
  dietary: Utensils,
  transport: Car,
  home: House,
  home_location: House,
  city: Building2,
  favorite_city: Heart,
  budget: Wallet,
  travel_preference: Luggage,
  weather_preference: CloudSun,
  trip_style: Sparkles,
}

export const EXPENSE_ICONS: Record<string, LucideIcon> = {
  交通: Car,
  餐饮: Utensils,
  住宿: Hotel,
  通讯: Smartphone,
  办公: Briefcase,
  娱乐: Clapperboard,
  其他: Package,
}

export function preferenceIcon(type: string | undefined): LucideIcon {
  return (type && PREFERENCE_ICONS[type]) || Pin
}

export function expenseIcon(category: string | undefined): LucideIcon {
  return (category && EXPENSE_ICONS[category]) || Package
}

/** 供列表渲染用：保持声明顺序，与后端分类口径一致。 */
export const EXPENSE_CATEGORIES = Object.keys(EXPENSE_ICONS)
