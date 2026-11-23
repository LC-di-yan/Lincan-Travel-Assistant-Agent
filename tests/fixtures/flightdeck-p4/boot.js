// Injected into the disposable study copy only, never built into the app.
(() => {
  const mode = new URLSearchParams(location.search).get('p4')
  if (!['a', 'b'].includes(mode)) return
  const root = document.getElementById('root')
  const fine = matchMedia('(hover: hover) and (pointer: fine)')
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  const state = window.p4 = { ready: null, submit: null, state: 'static', samples: [], hoverAt: null, eligible: false }
  const tellParent = () => {
    if (parent !== window) parent.postMessage({ kind: 'flightdeck-study', ready: state.ready, submit: state.submit,
      exposed: state.samples.length > 0, motionEligible: state.eligible }, location.origin)
  }
  const resources = new PerformanceObserver(list => {
    for (const entry of list.getEntries()) {
      if (state.submit === null && new URL(entry.name).pathname === '/api/chat') {
        state.submit = entry.startTime
        tellParent()
      }
    }
  })
  resources.observe({ type: 'resource', buffered: true })
  let stop
  let queued = false
  let frame1 = 0
  let frame2 = 0
  let done = false
  let removeHover = () => {}
  const observer = new MutationObserver(ready)
  observer.observe(root, { subtree: true, childList: true })
  ready()
  function ready() {
    if (queued || done) return
    const plate = root.querySelector('.atlas-plate')
    const start = root.querySelector('.deck-action')
    if (!plate || !start || !root.querySelector('textarea')) return
    queued = true
    observer.disconnect()
    // Let the shared composer and static SVG paint before even permitting a fetch.
    frame1 = requestAnimationFrame(() => {
      frame2 = requestAnimationFrame(() => {
        if (done || !plate.isConnected || !start.isConnected) return
        state.ready = performance.now()
        state.eligible = fine.matches && !reduced.matches && document.documentElement.dataset.motion === 'standard' &&
          Boolean(plate.querySelector('.plate-map')?.getClientRects().length)
        tellParent()
        if (mode === 'b') {
          plate.addEventListener('pointermove', tryLoad, { passive: true })
          removeHover = () => plate.removeEventListener('pointermove', tryLoad)
        }
      })
    })
    function tryLoad(event) {
      if (event.pointerType !== 'mouse' || !fine.matches || reduced.matches || document.hidden ||
          document.documentElement.dataset.motion !== 'standard' ||
          !plate.querySelector('.plate-map')?.getClientRects().length) return
      removeHover()
      state.state = 'loading'
      state.hoverAt = performance.now()
      import('/p4-parallax.mjs').then(({ attachChartParallax }) => {
        if (done || !plate.isConnected) { state.state = 'detached'; return }
        stop = attachChartParallax(plate, {
          onSample(sample) {
            state.samples.push(sample)
            if (state.samples.length === 1) tellParent()
            if (state.samples.length > 800) state.samples.shift()
          },
          onFallback() { state.state = 'slow-fallback' },
        })
        state.state = 'armed'
      }).catch(() => { state.state = 'unavailable' })
    }
  }
  window.addEventListener('pagehide', () => {
    done = true
    cancelAnimationFrame(frame1)
    cancelAnimationFrame(frame2)
    observer.disconnect()
    resources.disconnect()
    removeHover()
    stop?.()
  }, { once: true })
})()
