// Prototype only: move the clipped contour strokes, not stations or the route.
export function attachChartParallax(plate, { onSample = () => {}, onFallback = () => {} } = {}) {
  const map = plate.querySelector('.plate-map')
  const contours = map?.querySelector('g[clip-path] > g')
  if (!contours) return () => {}

  let frame = 0
  let rect = null
  let point = null
  let previous = null
  let slowSince = null
  let moving = false
  let onScreen = false
  const input = matchMedia('(hover: hover) and (pointer: fine)')
  const reduce = matchMedia('(prefers-reduced-motion: reduce)')
  const isAllowed = () => input.matches && !reduce.matches && document.documentElement.dataset.motion === 'standard' &&
    onScreen && !document.hidden && plate.isConnected

  function reset() {
    if (frame) cancelAnimationFrame(frame)
    frame = 0
    rect = point = previous = slowSince = null
    moving = false
    contours.style.removeProperty('transform')
  }

  function draw(now) {
    frame = 0
    if (!isAllowed() || !point) return reset()
    rect ??= map.getBoundingClientRect()
    if (!rect.width || !rect.height) return reset()
    const { x, y, at } = point
    const cadence = previous && at - previous.at < 80 ? now - previous.now : null
    if (cadence !== null && cadence > 24) {
      slowSince ??= previous.now
      if (now - slowSince >= 1000) {
        detach()
        onFallback()
        return
      }
    } else slowSince = null
    const clamp = ratio => Math.min(1, Math.max(-1, ratio))
    const dx = 4 * clamp((x - rect.left) / rect.width * 2 - 1)
    const dy = 3 * clamp((y - rect.top) / rect.height * 2 - 1)
    // Transform values are in SVG view-box units. Limit the visible displacement.
    const scale = Math.max(rect.width / 480, rect.height / 300, 1)
    contours.style.transform = `translate(${(dx / scale).toFixed(2)}px, ${(dy / scale).toFixed(2)}px)`
    onSample({ latency: performance.now() - at, cadence })
    previous = { now, at }
    moving = true
  }

  function move(event) {
    if (event.pointerType !== 'mouse' || !isAllowed()) return
    point = { x: event.clientX, y: event.clientY, at: performance.now() }
    if (!frame) frame = requestAnimationFrame(draw)
  }
  const invalidate = () => { rect = null }
  const policy = () => { if (!isAllowed()) reset() }
  const intersection = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting
    policy()
  })
  const mutation = new MutationObserver(() => {
    if (!plate.isConnected) detach()
    else policy()
  })
  function detach() {
    reset()
    intersection.disconnect()
    mutation.disconnect()
    plate.removeEventListener('pointermove', move)
    plate.removeEventListener('pointerleave', reset)
    window.removeEventListener('resize', policy)
    window.removeEventListener('resize', invalidate)
    window.removeEventListener('scroll', invalidate, true)
    document.removeEventListener('visibilitychange', policy)
    input.removeEventListener('change', policy)
    reduce.removeEventListener('change', policy)
  }
  intersection.observe(map)
  mutation.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] })
  // Observe the root so changing sessions or leaving the homepage cleans up.
  mutation.observe(document.getElementById('root'), { childList: true, subtree: true })
  plate.addEventListener('pointermove', move, { passive: true })
  plate.addEventListener('pointerleave', reset, { passive: true })
  window.addEventListener('resize', policy, { passive: true })
  window.addEventListener('resize', invalidate, { passive: true })
  window.addEventListener('scroll', invalidate, { capture: true, passive: true })
  document.addEventListener('visibilitychange', policy)
  input.addEventListener('change', policy)
  reduce.addEventListener('change', policy)
  return Object.assign(detach, { active: () => moving })
}
