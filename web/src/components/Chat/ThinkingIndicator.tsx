export function ThinkingIndicator({ status }: { status: string }) {
  const labels: Record<string, string> = {
    analyzing_intent: '正在分析意图...',
    dispatching: '正在调度智能体...',
    '': '思考中...',
  }
  return (
    <div className="flex items-center gap-3 px-5 py-4 animate-fade-in-up">
      <img
        src="/images/illustrations/thinking.svg"
        alt="思考中"
        width={60}
        height={20}
        className="opacity-80"
      />
      <span className="text-sm text-[var(--text-muted)] font-medium">
        {labels[status] || status}
      </span>
    </div>
  )
}
