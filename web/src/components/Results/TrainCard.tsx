import { CardShell } from './CardShell'

type Train = {
  train_no?: string
  train_type?: string
  from_station?: string
  to_station?: string
  depart_time?: string
  arrive_time?: string
  duration?: string
  second_class?: string
  first_class?: string
  business?: string
  hard_sleeper?: string
  soft_sleeper?: string
  hard_seat?: string
  no_seat?: string
}

function SeatChip({ label, value }: { label: string; value?: string }) {
  const v = (value || '').trim()
  const has = v && v !== '无' && v !== '--' && v !== '*'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-[2px] border px-1.5 py-0.5 text-[11px] ${
        has ? 'border-rule bg-paper text-ink' : 'border-rule/60 bg-transparent text-ink-3'
      }`}
    >
      <span className="text-ink-2">{label}</span>
      <span className={has ? 'font-medium' : ''}>{has ? v : '无'}</span>
    </span>
  )
}

export function TrainCard({ data }: { data: Record<string, unknown> }) {
  const results = ((data.results as Record<string, unknown>) || data) as Record<string, unknown>
  const trains = (results.trains || []) as Train[]
  const date = (results.date as string) || ''
  const from = (results.from as string) || ''
  const to = (results.to as string) || ''
  const summary = (results.summary as string) || (data.answer as string) || ''
  const total = (results.total as number) || trains.length
  const expanded = Boolean(results.expanded || data.expanded)

  return (
    <CardShell agentName="train_ticket">
      <div className="flex items-baseline justify-between gap-3 border-b border-rule px-4 py-3">
        <div>
          <div className="mono-label text-[10px] tracking-[0.18em] text-ink-3">ALIGO / RAIL</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[15px] font-medium text-ink">
              {from && to ? `${from} → ${to}` : '火车票'}
            </span>
            {date && (
              <span className="mono-label rounded-[2px] border border-rule px-1.5 py-0.5 text-[11px] text-ink-2">
                {date}
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[13px] text-ink">{total} 趟</div>
          <div className="text-[11px] text-ink-3">{expanded ? '已展开全部' : '12306 实时余票'}</div>
        </div>
      </div>

      {trains.length === 0 ? (
        <div className="px-4 py-6 text-[13px] text-ink-2">
          {summary || '该日期暂无余票，可以换个日期或看看其他交通方式。'}
        </div>
      ) : (
        <ul
          className={
            expanded
              ? 'divide-y divide-rule/70'
              : 'max-h-[520px] divide-y divide-rule/70 overflow-y-auto'
          }
        >
          {trains.map((t, i) => (
            <li key={`${t.train_no}-${i}`} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-[14px] font-medium text-ink">{t.train_no}</span>
                <span className="text-[11px] text-ink-3">{t.train_type}</span>
                <span className="text-[13px] text-ink">
                  {t.depart_time} → {t.arrive_time}
                </span>
                <span className="text-[11px] text-ink-3">{t.duration}</span>
                <span className="text-[11px] text-ink-3">
                  {t.from_station} → {t.to_station}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <SeatChip label="二等座" value={t.second_class} />
                <SeatChip label="一等座" value={t.first_class} />
                <SeatChip label="商务座" value={t.business} />
                {(t.hard_sleeper && t.hard_sleeper !== '无') && (
                  <SeatChip label="硬卧" value={t.hard_sleeper} />
                )}
                {(t.soft_sleeper && t.soft_sleeper !== '无') && (
                  <SeatChip label="软卧" value={t.soft_sleeper} />
                )}
                {(t.hard_seat && t.hard_seat !== '无') && <SeatChip label="硬座" value={t.hard_seat} />}
                {(t.no_seat && t.no_seat !== '无') && <SeatChip label="无座" value={t.no_seat} />}
              </div>
            </li>
          ))}
        </ul>
      )}

      {summary && trains.length > 0 && !expanded && (
        <div className="border-t border-rule px-4 py-2 text-[11px] text-ink-3">{summary}</div>
      )}
    </CardShell>
  )
}
