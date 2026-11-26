import { Component, Suspense, type ReactNode } from 'react'

interface Props {
  label: string
  children: ReactNode
  fallback?: ReactNode
  failure?: ReactNode
}

export class DeferredRegion extends Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    const { label, children, fallback, failure } = this.props
    if (this.state.failed) {
      return failure === undefined
        ? <p role="alert" className="p-4 text-sm text-ink-2">{label}暂时无法加载。可刷新页面后再试。</p>
        : failure
    }
    return <Suspense fallback={fallback === undefined
      ? <p role="status" className="p-4 text-sm text-ink-2">正在加载{label}…</p> : fallback}>{children}</Suspense>
  }
}
