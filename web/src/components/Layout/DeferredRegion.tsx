import { Component, Suspense, type ReactNode } from 'react'

export class DeferredRegion extends Component<{ label: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    const { label, children } = this.props
    if (this.state.failed) {
      return <p role="alert" className="p-4 text-sm text-ink-2">{label}暂时无法加载。可刷新页面后再试。</p>
    }
    return <Suspense fallback={<p role="status" className="p-4 text-sm text-ink-2">正在加载{label}…</p>}>{children}</Suspense>
  }
}
