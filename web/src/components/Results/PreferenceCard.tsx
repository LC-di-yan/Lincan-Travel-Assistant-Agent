import { CheckCircle } from 'lucide-react'
import { CardShell } from './CardShell'
import { AgentIcon } from '../Icons'

export function PreferenceCard({ data }: { data: Record<string, unknown> }) {
  const prefs = data.preferences as Record<string, unknown> | undefined
  const prefList = prefs?.preferences as { type: string; value: string; action?: string }[] | undefined

  return (
    <CardShell agentName="preference">
      <div className="p-4 space-y-2.5">
        <h4 className="font-semibold text-sm flex items-center gap-1.5">
          <AgentIcon agentName="preference" size={16} /> 偏好已更新
        </h4>
        {prefList ? (
          <div className="space-y-1.5">
            {prefList.map((p, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <CheckCircle size={12} className="text-[var(--success)]" />
                <span className="text-[var(--text-muted)]">{p.type}:</span>
                <span className="font-medium">{p.value}</span>
                {p.action && (
                  <span className="text-xs px-1.5 py-0.5 rounded-full"
                    style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}>
                    {p.action === 'append' ? '追加' : '替换'}
                  </span>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[var(--text-secondary)]">偏好已保存</p>
        )}
      </div>
    </CardShell>
  )
}
