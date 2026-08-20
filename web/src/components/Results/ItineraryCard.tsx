import { useState, useRef, useEffect } from 'react'
import { Clock, Utensils, ChevronDown, ChevronRight, StickyNote, MapPin, Pencil } from 'lucide-react'
import type { Itinerary, DailyPlan, Activity } from '../../api/types'
import { CardShell } from './CardShell'
import { ExportButton } from './ExportButton'
import { CityIllustration } from '../Illustrations'

const activityIcons: Record<string, string> = {
  '交通': '🚄', '景点': '🏛️', '餐饮': '🍽️', '住宿': '🏨', '会议': '📋', '购物': '🛍️',
}

function getActivityIcon(activity?: string): string {
  if (!activity) return '📌'
  for (const [key, icon] of Object.entries(activityIcons)) {
    if (activity.includes(key)) return icon
  }
  return '📌'
}

/** 内联可编辑活动名称：点击即改，Enter/失焦保存，Esc 取消 */
function EditableActivityName({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { setDraft(value) }, [value])

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  const commit = () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== value) onChange(trimmed)
    setEditing(false)
  }

  const cancel = () => { setDraft(value); setEditing(false) }

  if (editing) {
    return (
      <input
        ref={inputRef}
        className="font-medium bg-[var(--bg-primary)] border border-[var(--accent)] rounded px-1 py-0.5 text-sm outline-none min-w-0"
        style={{ color: 'var(--text-primary)' }}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter')  { e.preventDefault(); commit() }
          if (e.key === 'Escape') { e.preventDefault(); cancel() }
        }}
      />
    )
  }

  return (
    <span
      className="font-medium cursor-pointer group inline-flex items-center gap-1 hover:text-[var(--accent)] transition-colors"
      onClick={() => { setDraft(value); setEditing(true) }}
      title="点击编辑活动名称"
    >
      {value}
      <Pencil size={11} className="opacity-0 group-hover:opacity-60 transition-opacity flex-shrink-0" />
    </span>
  )
}

function DailyPlanItem({ plan }: { plan: DailyPlan }) {
  const [open, setOpen] = useState(true)
  /** 本地覆盖：dayIndex 与 actIndex 组合 → 用户编辑后的名称 */
  const [nameOverrides, setNameOverrides] = useState<Record<number, string>>({})

  const getDisplayName = (act: Activity, idx: number) =>
    nameOverrides[idx] ?? act.activity ?? '未命名活动'

  const handleNameChange = (idx: number, newName: string) => {
    setNameOverrides((prev) => ({ ...prev, [idx]: newName }))
  }

  return (
    <div className="relative pl-8 pb-4">
      <div className="absolute left-3 top-1 bottom-0 w-0.5" style={{ backgroundColor: 'var(--border)' }} />
      <div className="absolute left-1.5 top-1.5 w-3 h-3 rounded-full border-2 animate-glow-pulse"
        style={{ borderColor: 'var(--accent)', backgroundColor: 'var(--bg-primary)' }} />

      <button onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 font-semibold text-sm mb-1 hover:text-[var(--accent)] transition-colors">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {plan.day}
      </button>

      {open && (
        <div className="space-y-2 mt-1">
          {(plan.activities || []).map((act, i) => {
            const displayName = getDisplayName(act, i)
            return (
              <div key={i}
                className="flex gap-2 text-sm p-2.5 rounded-xl transition-all hover:shadow-sm card-hover"
                style={{ backgroundColor: 'var(--bg-secondary)' }}>
                <span className="flex-shrink-0 text-base">{getActivityIcon(displayName)}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    {act.time && (
                      <span className="text-xs text-[var(--text-muted)] flex items-center gap-1">
                        <Clock size={10} />{act.time}
                      </span>
                    )}
                    <EditableActivityName
                      value={displayName}
                      onChange={(v) => handleNameChange(i, v)}
                    />
                  </div>
                  {act.description && <p className="text-xs text-[var(--text-secondary)] mt-0.5">{act.description}</p>}
                  {act.transport && <span className="text-xs text-[var(--accent)]">🚗 {act.transport}</span>}
                </div>
              </div>
            )
          })}

          {(plan.meals?.lunch || plan.meals?.dinner) && (
            <div className="flex gap-3 text-xs text-[var(--text-secondary)] ml-1">
              {plan.meals?.lunch && <span><Utensils size={10} className="inline" /> 午: {plan.meals.lunch}</span>}
              {plan.meals?.dinner && <span><Utensils size={10} className="inline" /> 晚: {plan.meals.dinner}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function extractDestination(itinerary: Itinerary): string | undefined {
  const title = itinerary.title || ''
  const match = title.match(/去(.+?)(?:出差|旅行|旅游|开会|培训|考察)/)
  if (match) return match[1]
  const match2 = title.match(/到(.+?)(?:出差|旅行|旅游|开会|培训|考察)/)
  if (match2) return match2[1]
  return undefined
}

export function ItineraryCard({ data }: { data: Record<string, unknown> }) {
  const itinerary = (data.itinerary || data) as Itinerary
  if (!itinerary?.title) return null

  const destination = extractDestination(itinerary)

  return (
    <CardShell agentName="itinerary_planning">
      <div className="relative overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between relative z-10"
          style={{ background: 'linear-gradient(135deg, var(--accent), #7c3aed)' }}>
          <div className="flex-1">
            <h3 className="text-white font-bold text-sm">{itinerary.title}</h3>
            {itinerary.duration && <p className="text-white/80 text-xs mt-0.5">{itinerary.duration}</p>}
            {/* Route overview */}
            <div className="flex items-center gap-1.5 mt-2">
              <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-white/20 text-white/90">
                <MapPin size={8} /> 行程规划
              </span>
            </div>
          </div>
          <ExportButton itinerary={itinerary} />
        </div>
        {/* City illustration watermark */}
        <div className="absolute right-0 bottom-0 w-32 h-24 opacity-[0.06] pointer-events-none">
          <CityIllustration city={destination} className="w-full h-full object-contain" />
        </div>
      </div>

      <div className="p-4" style={{ backgroundColor: 'var(--bg-elevated)' }}>
        {itinerary.daily_plans?.map((plan, i) => (
          <DailyPlanItem key={i} plan={plan} />
        ))}

        {itinerary.notes && itinerary.notes.length > 0 && (
          <div className="mt-3 p-3 rounded-xl text-xs" style={{ backgroundColor: 'var(--warning-light)' }}>
            <div className="flex items-center gap-1 font-medium mb-1">
              <StickyNote size={12} /> 注意事项
            </div>
            <ul className="list-disc list-inside space-y-0.5 text-[var(--text-secondary)]">
              {itinerary.notes.map((note, i) => <li key={i}>{note}</li>)}
            </ul>
          </div>
        )}
      </div>
    </CardShell>
  )
}
