import { EvidenceBand, FlightResult } from './FlightResult'
import { PreferenceTypeIcon } from '../Icons'
import { preferenceLabel } from '../../utils/preferenceLabels'

export function PreferenceCard({ data }: { data: Record<string, unknown> }) {
  const raw = data.preferences as unknown
  const prefList = (Array.isArray(raw)
    ? raw
    : (raw as { preferences?: unknown } | undefined)?.preferences) as
    | { type: string; value: string | string[]; action?: string }[]
    | undefined

  return (
    <FlightResult agent="preference" kind="偏好回执" title={prefList?.length ? '偏好已保存' : '偏好结果'}>
      {prefList?.length ? <EvidenceBand label="已保存" status="保存不等于授权用于规划" tone="confirmed" /> : null}

      <div className="px-4 py-2">
        {!prefList || prefList.length === 0 ? (
          <p className="py-3 text-center text-[12px] text-ink-3">没有识别到新的偏好</p>
        ) : (
          prefList.map((p, i) => (
            <div key={i} className="flex items-start gap-3 border-b border-rule py-2.5 last:border-0">
              <PreferenceTypeIcon kind={p.type} className="mt-1 shrink-0 text-ink-3" />
              <div className="min-w-0 flex-1">
                <div className="text-[10px] tracking-[0.06em] text-ink-3">{preferenceLabel(p.type)}</div>
                <div className="mt-0.5 text-[13px] leading-6 text-ink">
                  {Array.isArray(p.value) ? p.value.join('、') : p.value}
                </div>
              </div>
              <span className="shrink-0 text-[10px] text-ok">
                {p.action === 'append' ? '已追加' : '已更新'}
              </span>
            </div>
          ))
        )}
      </div>
    </FlightResult>
  )
}
