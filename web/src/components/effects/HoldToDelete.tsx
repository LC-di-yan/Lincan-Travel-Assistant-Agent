'use client'

/**
 * HoldToDelete —— 长按确认删除按钮。
 *
 * 按住（指针或键盘 Space / Enter）后 3px 的进度环在 holdMs 内线性填满，只有填满才触发一次
 * onConfirm；提前松开、指针移出、pointercancel、keyup 或 Escape 都会取消，环按已推进的比例
 * 在 resetMs 内退回空心。进度只由唯一的 requestAnimationFrame 循环直接写 stroke-dashoffset，
 * 不经过 React state，也不动画任何布局属性。
 *
 * 破坏性操作的等待是安全语义而不是装饰：prefers-reduced-motion 下 holdMs 不缩短、进度仍按
 * 真实时间推进，只有取消 / 删除的状态切换压到 ≤1ms。
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import {
  animate, motion, useMotionValue, useTransform,
  type AnimationPlaybackControls, type MotionStyle,
} from 'motion/react'
import { GlassSurface } from './LiquidGlassButton'

const BOX_WIDTH = 216
const BOX_HEIGHT = 52
const BOX_RADIUS = 14
const RING_OFFSET = 4
const HOLD_MS = 1500
const RESET_MS = 180
const RING_WIDTH = 3
const TAP_MS = 200
const STATE_SWITCH_MS = 200
const REDUCED_SWITCH_MS = 1
const RING_CIRCUMFERENCE = 100

const IDLE_BORDER = 'rgba(237, 238, 240, 0.16)'
const IDLE_BG = 'rgba(237, 238, 240, 0.04)'
const IDLE_TEXT = '#edeef0'
const HOLD_BORDER = 'rgba(201, 244, 90, 0.55)'
const HOLD_BG = 'rgba(201, 244, 90, 0.10)'
const DELETED_BORDER = 'rgba(74, 222, 128, 0.55)'
const DELETED_BG = 'rgba(74, 222, 128, 0.12)'
const DELETED_TEXT = '#4ade80'
const TRACK_COLOR = 'rgba(201, 244, 90, 0.14)'
const PROGRESS_COLOR = '#c9f45a'
const CONFIRMED_COLOR = '#4ade80'
const FOCUS_COLOR = '#C9F45A'
const STYLE_FLAG = 'data-hold-to-delete'
/** 玻璃行复用 LiquidGlassButton 的同一套按压弹簧（按下 640/34/0.7，松手 460/≈14.4/0.7）。 */
const GLASS_PRESS_SPRING = { type: 'spring' as const, stiffness: 640, damping: 34, mass: 0.7 }
const GLASS_RELEASE_SPRING = { type: 'spring' as const, stiffness: 460, damping: 14.4, mass: 0.7 }
const GLASS_HEIGHT = 64
const GLASS_RADIUS = 22

type Phase = 'idle' | 'holding' | 'cancelling' | 'confirmed'

export interface HoldToDeleteProps {
  onConfirm: () => void
  deleted?: boolean
  onUndo?: () => void
  onActivate?: () => void
  holdMs?: number
  resetMs?: number
  ringWidth?: number
  width?: number | string
  height?: number | string
  tapMs?: number
  align?: 'center' | 'left'
  label?: string
  deletedLabel?: string
  ariaLabel?: string
  /** plain：原来的深色胶囊；glass：换成液态玻璃面层。 */
  surface?: 'plain' | 'glass'
  /** 当前打开的那条对话：玻璃边缘换成航线色。 */
  active?: boolean
  children?: ReactNode
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return true
  const policy = document.documentElement.dataset.motion
  return typeof policy === 'string' && policy !== 'standard'
}

function ensureStyles(): void {
  if (document.querySelector('style[' + STYLE_FLAG + ']')) return
  const style = document.createElement('style')
  style.setAttribute(STYLE_FLAG, '')
  style.textContent = [
    '.hold-to-delete{position:relative;display:flex;align-items:center;box-sizing:border-box;',
    'border-style:solid;border-width:1px;border-radius:' + BOX_RADIUS + 'px;',
    'padding:0 16px;font-size:13px;font-weight:600;line-height:1.15;',
    'cursor:pointer;user-select:none;-webkit-user-select:none;',
    '-webkit-tap-highlight-color:transparent;touch-action:manipulation}',
    '.hold-to-delete:focus-visible{outline:2px solid ' + FOCUS_COLOR + ';outline-offset:3px}',
    '.hold-to-delete__ring{position:absolute;overflow:visible;pointer-events:none}',
    '.hold-to-delete__live{position:absolute;width:1px;height:1px;margin:-1px;padding:0;',
    'border:0;overflow:hidden;white-space:nowrap;clip-path:inset(50%)}',
    '.hold-to-delete__icon{display:flex;align-items:center;justify-content:center;flex:none}',
    '.hold-to-delete__text{display:block;white-space:nowrap}',
    '.hold-to-delete__status{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;height:100%}',
  ].join('')
  document.head.appendChild(style)
}

export function HoldToDelete({
  onConfirm,
  deleted,
  onUndo,
  onActivate,
  holdMs = HOLD_MS,
  resetMs = RESET_MS,
  ringWidth = RING_WIDTH,
  width = BOX_WIDTH,
  height = BOX_HEIGHT,
  tapMs = TAP_MS,
  align = 'center',
  label = '长按删除',
  deletedLabel = '已删除 / Deleted',
  ariaLabel,
  surface = 'plain',
  active = false,
  children,
}: HoldToDeleteProps) {
  const glass = surface === 'glass'
  const glassPress = useMotionValue(0)
  const glassScaleX = useTransform(glassPress, (value) => 1 + 0.05 * value)
  const glassScaleY = useTransform(glassPress, (value) => 1 - 0.14 * value)
  const pressAnim = useRef<AnimationPlaybackControls | null>(null)
  const ringRef = useRef<SVGRectElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const resetTimerRef = useRef<number | null>(null)
  const startRef = useRef(0)
  const pressRef = useRef(0)
  const confirmedRef = useRef(false)
  const mountedRef = useRef(true)
  const phaseRef = useRef<Phase>('idle')
  const confirmHandler = useRef(onConfirm)

  useEffect(() => {
    confirmHandler.current = onConfirm
  }, [onConfirm])
  const [phase, setPhaseState] = useState<Phase>('idle')
  const [internalDeleted, setInternalDeleted] = useState(false)
  const [announce, setAnnounce] = useState('')
  const removed = deleted ?? internalDeleted
  const seconds = (holdMs / 1000).toFixed(1)

  const setPhase = useCallback((next: Phase) => {
    phaseRef.current = next
    if (mountedRef.current) setPhaseState(next)
  }, [])

  useEffect(() => {
    ensureStyles()
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
      if (resetTimerRef.current !== null) window.clearTimeout(resetTimerRef.current)
      resetTimerRef.current = null
      pressAnim.current?.stop()
      pressAnim.current = null
    }
  }, [])

  /** 玻璃行的按压：按住压扁，松手过冲一次；reduced-motion 下不动形。 */
  const drivePress = useCallback((to: 0 | 1) => {
    if (!glass || prefersReducedMotion()) return
    pressAnim.current?.stop()
    pressAnim.current = animate(glassPress, to, to === 1 ? GLASS_PRESS_SPRING : GLASS_RELEASE_SPRING)
  }, [glass, glassPress])

  const clearResetTimer = useCallback(() => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current)
      resetTimerRef.current = null
    }
  }, [])

  const paint = useCallback((progress: number) => {
    const node = ringRef.current
    if (node) node.style.strokeDashoffset = String(RING_CIRCUMFERENCE * (1 - progress))
  }, [])

  const stopLoop = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [])

  const confirm = useCallback(() => {
    if (confirmedRef.current) return
    confirmedRef.current = true
    stopLoop()
    clearResetTimer()
    paint(1)
    setPhase('confirmed')
    setAnnounce('已删除')
    drivePress(0)
    confirmHandler.current()
  }, [clearResetTimer, drivePress, paint, setPhase, stopLoop])

  const cancel = useCallback(() => {
    if (rafRef.current === null && phaseRef.current !== 'holding') return
    stopLoop()
    drivePress(0)
    const node = ringRef.current
    const reduced = prefersReducedMotion()
    const duration = reduced ? REDUCED_SWITCH_MS : resetMs
    if (node) {
      node.style.transition = 'stroke-dashoffset ' + duration + 'ms linear'
      node.style.strokeDashoffset = String(RING_CIRCUMFERENCE)
    }
    clearResetTimer()
    resetTimerRef.current = window.setTimeout(() => {
      resetTimerRef.current = null
      const ring = ringRef.current
      if (ring) ring.style.removeProperty('transition')
      if (mountedRef.current && !confirmedRef.current) setPhase('idle')
    }, duration)
    if (phaseRef.current === 'holding') {
      setPhase('cancelling')
      setAnnounce('已取消删除')
    }
  }, [clearResetTimer, drivePress, resetMs, setPhase, stopLoop])

  const begin = useCallback(() => {
    if (removed || confirmedRef.current || rafRef.current !== null) return
    clearResetTimer()
    drivePress(1)
    const node = ringRef.current
    if (node) {
      node.style.transition = 'none'
      node.style.strokeDashoffset = String(RING_CIRCUMFERENCE)
    }
    startRef.current = performance.now()
    setPhase('holding')
    setAnnounce('开始按住，继续按住 ' + seconds + ' 秒即可删除')
    const tick = () => {
      const progress = Math.min(1, (performance.now() - startRef.current) / holdMs)
      paint(progress)
      if (progress >= 1) {
        rafRef.current = null
        confirm()
        return
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
  }, [clearResetTimer, confirm, drivePress, holdMs, paint, removed, seconds, setPhase])

  useEffect(() => {
    stopLoop()
    clearResetTimer()
    if (removed) {
      paint(1)
      return
    }
    confirmedRef.current = false
    setPhase('idle')
    const node = ringRef.current
    if (node) {
      node.style.removeProperty('transition')
      node.style.strokeDashoffset = String(RING_CIRCUMFERENCE)
    }
  }, [clearResetTimer, paint, removed, setPhase, stopLoop])

  const handlePointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (removed || event.button !== 0) return
    pressRef.current = performance.now()
    begin()
  }

  const handlePointerUp = () => {
    const held = performance.now() - pressRef.current
    cancel()
    if (held > tapMs && !confirmedRef.current) pressRef.current = 0
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape') {
      if (phaseRef.current === 'holding') {
        event.preventDefault()
        cancel()
      }
      return
    }
    if (event.key !== ' ' && event.key !== 'Enter') return
    event.preventDefault()
    if (event.repeat || removed) return
    pressRef.current = performance.now()
    begin()
  }

  const handleKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== ' ' && event.key !== 'Enter') return
    event.preventDefault()
    cancel()
  }

  const handleClick = () => {
    if (removed) {
      setInternalDeleted(false)
      setAnnounce('')
      onUndo?.()
      return
    }
    const held = performance.now() - pressRef.current
    if (pressRef.current === 0 || held > tapMs) return
    onActivate?.()
  }

  const reduced = prefersReducedMotion()
  const switchMs = reduced ? REDUCED_SWITCH_MS : STATE_SWITCH_MS
  const holding = !removed && (phase === 'holding' || phase === 'cancelling')
  const border = removed ? DELETED_BORDER : holding ? HOLD_BORDER : IDLE_BORDER
  const background = removed ? DELETED_BG : holding ? HOLD_BG : IDLE_BG
  const color = removed ? DELETED_TEXT : IDLE_TEXT
  const ringTrack = glass ? 'var(--lg-ring-track)' : TRACK_COLOR
  const ringProgressColor = glass
    ? (phase === 'confirmed' || removed ? 'var(--lg-ring-ok)' : 'var(--lg-ring)')
    : (phase === 'confirmed' || removed ? CONFIRMED_COLOR : PROGRESS_COLOR)
  const ringRadius = (glass ? GLASS_RADIUS : BOX_RADIUS) + RING_OFFSET
  // 玻璃行平时不画轨道环：玻璃本身已经是「按住的按钮」，环只在你真的按住时出现。
  const trackOpacity = removed ? 0 : glass ? (holding ? 1 : 0) : 1

  const style: MotionStyle = {
    width,
    height,
    minWidth: width,
    borderColor: border,
    backgroundColor: background,
    color,
    justifyContent: align === 'left' ? 'flex-start' : 'center',
    gap: 10,
    transition:
      'background-color ' + switchMs + 'ms linear, border-color ' + switchMs +
      'ms linear, color ' + switchMs + 'ms linear',
  }

  const glassStyle: MotionStyle = {
    width: '100%',
    minWidth: 0,
    height: GLASS_HEIGHT,
    borderWidth: 0,
    borderRadius: GLASS_RADIUS,
    backgroundColor: 'transparent',
    color: 'var(--lg-ink)',
    padding: 0,
    transformOrigin: '50% 70%',
    scaleX: glassScaleX,
    scaleY: glassScaleY,
  }

  const ringStyle: CSSProperties = {
    left: -RING_OFFSET,
    top: -RING_OFFSET,
    width: 'calc(100% + ' + RING_OFFSET * 2 + 'px)',
    height: 'calc(100% + ' + RING_OFFSET * 2 + 'px)',
  }

  const ring = (
    <svg aria-hidden="true" className="hold-to-delete__ring" style={ringStyle}>
      <rect
        x="0"
        y="0"
        width="100%"
        height="100%"
        rx={ringRadius}
        fill="none"
        stroke={ringTrack}
        strokeWidth={ringWidth}
        strokeDasharray={String(RING_CIRCUMFERENCE)}
        strokeDashoffset={String(RING_CIRCUMFERENCE)}
        style={{ opacity: trackOpacity, transition: 'opacity ' + switchMs + 'ms linear' }}
      />
      <rect
        ref={ringRef}
        x="0"
        y="0"
        width="100%"
        height="100%"
        rx={ringRadius}
        fill="none"
        stroke={ringProgressColor}
        strokeWidth={ringWidth}
        strokeLinecap="round"
        pathLength={RING_CIRCUMFERENCE}
        strokeDasharray={String(RING_CIRCUMFERENCE)}
        strokeDashoffset={String(RING_CIRCUMFERENCE)}
        style={{
          opacity: removed ? 0 : 1,
          transition: 'opacity ' + switchMs + 'ms linear',
          ...(removed ? { strokeDashoffset: String(RING_CIRCUMFERENCE) } : {}),
        }}
      />
    </svg>
  )

  const content = removed ? (
    <span className="hold-to-delete__status">
      <span className="hold-to-delete__icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
          strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12.5 9.5 18 20 6.5" />
        </svg>
      </span>
      <span className="hold-to-delete__text">{deletedLabel}</span>
    </span>
  ) : (children ?? <span className="hold-to-delete__text">{label}</span>)

  return (
    <>
      <motion.button
        type="button"
        className={glass ? 'hold-to-delete hold-to-delete--glass lg-button' : 'hold-to-delete'}
        style={glass ? glassStyle : style}
        aria-label={ariaLabel ?? '按住 ' + seconds + ' 秒删除'}
        aria-current={active ? 'true' : undefined}
        data-active={active ? 'true' : undefined}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerLeave={cancel}
        onPointerCancel={cancel}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        onClick={handleClick}
        onContextMenu={(event) => event.preventDefault()}
      >
        {glass
          ? <GlassSurface overlay={ring}>{content}</GlassSurface>
          : <>{ring}{content}</>}
      </motion.button>
      <span className="hold-to-delete__live" role="status" aria-live="polite">
        {announce}
      </span>
    </>
  )
}

export default HoldToDelete
