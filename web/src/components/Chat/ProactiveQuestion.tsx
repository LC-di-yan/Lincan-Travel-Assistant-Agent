export function ProactiveQuestion({ question }: { question: string }) {
  return (
    <aside aria-label="助手的后续提问"
      className="flex w-full items-start gap-3 rounded-[2px] border border-rule bg-paper-raised px-3 py-2.5">
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-[2px] border border-accent font-mono text-[11px] font-bold text-accent"
      >
        ?
      </span>
      <span className="min-w-0 flex-1 text-[13px] leading-6 text-ink">{question}</span>
    </aside>
  )
}
