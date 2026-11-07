import { Mic, Moon, Newspaper, Sun, type LucideIcon } from 'lucide-react'

/** 语音人格图标：按 persona id 映射。
 *  后端 /api/tts/personas 仍返回 emoji 字段（保持 API 兼容），
 *  但前端不再渲染它——改用与全站一致的 lucide 描边图标。 */
export const PERSONA_ICONS: Record<string, LucideIcon> = {
  loli_guide: Mic,
  soda_senior: Sun,
  baihua_anchor: Newspaper,
  chloe_calm: Moon,
}

export const PERSONA_FALLBACK_ICON = Mic
