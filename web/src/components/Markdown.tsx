import { lazy, Suspense } from 'react'

const ReactMarkdown = lazy(() => import('react-markdown'))

export function Markdown({ children }: { children: string }) {
  return (
    <Suspense fallback={<div className="whitespace-pre-wrap">{children}</div>}>
      <ReactMarkdown>{children}</ReactMarkdown>
    </Suspense>
  )
}
