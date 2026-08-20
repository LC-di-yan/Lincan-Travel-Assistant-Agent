interface JourneyProgressProps {
  total: number
  completed: number
}

export function JourneyProgress({ total, completed }: JourneyProgressProps) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0

  return (
    <div className="px-4 py-1.5">
      <div className="h-1 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-600 ease-out"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, var(--accent), #10b981)',
          }}
        />
      </div>
    </div>
  )
}
