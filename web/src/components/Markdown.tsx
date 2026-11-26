import { lazy } from 'react'
import { DeferredRegion } from './Layout/DeferredRegion'
import { normalizeReplyMarkdown } from '../utils/replyMarkdown'

const ReactMarkdown = lazy(() => import('react-markdown'))

export function Markdown({ children }: { children: string }) {
  const plain = <div className="whitespace-pre-wrap">{children}</div>
  return (
    <DeferredRegion label="回复排版" fallback={plain} failure={plain}>
      <ReactMarkdown>{normalizeReplyMarkdown(children)}</ReactMarkdown>
    </DeferredRegion>
  )
}
