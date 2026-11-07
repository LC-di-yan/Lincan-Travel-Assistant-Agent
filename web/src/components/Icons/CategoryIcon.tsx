import { Pin, Package } from 'lucide-react'
import { EXPENSE_ICONS, PREFERENCE_ICONS } from './categoryIcons'

interface CategoryIconProps {
  /** preference.type 或费用分类名 */
  kind: string | undefined
  size?: number
  className?: string
}

export function PreferenceTypeIcon({ kind, size = 14, className }: CategoryIconProps) {
  const Icon = PREFERENCE_ICONS[kind ?? ''] ?? Pin
  return <Icon size={size} strokeWidth={1.5} className={className} aria-hidden="true" />
}

export function ExpenseCategoryIcon({ kind, size = 14, className }: CategoryIconProps) {
  const Icon = EXPENSE_ICONS[kind ?? ''] ?? Package
  return <Icon size={size} strokeWidth={1.5} className={className} aria-hidden="true" />
}
