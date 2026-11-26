'use client'

/**
 * LiquidGlassButton —— 浮在航图花纹上的液态玻璃按钮。
 *
 * 几何照规格：292×64（最大 100%）、圆角 22、内容左右各 14px、10px 背板模糊、
 * 面层 1px 高光边；按下时按钮 scaleX 1+0.05p、scaleY 1-0.14p、整体上浮 1.5px，
 * 松手过冲一次再静止。指针只写 CSS 变量 --mx / --my，不经过 React state；
 * 只画 transform、opacity 与 backdrop-filter。
 *
 * 块下方不画厚边、不投影：玻璃直接贴在航图底纹上，边缘与厚度只由面层高光表达。
 *
 * 配色跟随主题（见 styles/liquid-glass.css）：亮色是纸白玻璃 + 墨色字，
 * 暗色回到提示词原值（白玻璃 + 白字）。GlassSurface / GlassContent 同时被
 * 聊天记录里的长按删除行复用，两块玻璃才是同一块材质。
 */

import {
  useCallback, useEffect, useRef,
  type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode,
} from 'react'
import {
  animate, motion, useMotionValue, useReducedMotion, useTransform,
  type AnimationPlaybackControls, type MotionStyle,
} from 'motion/react'
import { ArrowRight, MessageSquareText } from 'lucide-react'

const WIDTH = 292
const HEIGHT = 64
const RADIUS = 22
const DEFAULT_BLUR = 10
const DEFAULT_BOUNCE = 0.6

/** 按下：快速压扁，不回弹。 */
const PRESS_SPRING = { type: 'spring' as const, stiffness: 640, damping: 34, mass: 0.7 }
/** 松手：刚度 460 / 质量 0.7，阻尼由 bounce 折算（bounce 0.6 ⇒ 阻尼约 14.4，过冲一次）。 */
const RELEASE_STIFFNESS = 460
const RELEASE_MASS = 0.7
const PRESS_SPREAD = 0.05
const PRESS_SQUASH = 0.14
const HOVER_LIFT = 1.5
const HOVER_SCALE = 1.015
const GLOW_MAX = 0.9

/** 系统的 reduce 与站点自己的 data-motion 任一开启，就不做形变。 */
function motionOff(): boolean {
  if (typeof window === 'undefined') return false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return true
  const policy = document.documentElement.dataset.motion
  return typeof policy === 'string' && policy !== 'standard'
}

function releaseDamping(bounce: number) {
  const clamped = Math.min(Math.max(bounce, 0), 1)
  return 2 * Math.sqrt(RELEASE_STIFFNESS * RELEASE_MASS) * (1 - clamped)
}

export interface GlassSurfaceProps {
  blur?: number
  /** 面层着色；不传时用主题里的 --lg-face-tint。 */
  tint?: string
  /** 指针高光；prefers-reduced-motion 下宿主应传 false。 */
  highlight?: boolean
  /** 画在面层之上、不裁切的一层（长按删除的进度环）。 */
  overlay?: ReactNode
  children?: ReactNode
}

/** 玻璃本体：半透明面层 + 顶部高光 + 指针高光，不留厚边与投影。 */
export function GlassSurface({
  blur = DEFAULT_BLUR, tint, highlight = true, overlay, children,
}: GlassSurfaceProps) {
  const reduced = useReducedMotion() === true
  const shiftRef = useRef<HTMLSpanElement>(null)
  const glow = useMotionValue(0)
  const trackable = highlight && !reduced && !motionOff()

  const fadeGlow = useCallback((to: number) => {
    if (!trackable) return
    glow.stop()
    animate(glow, to, { duration: to > 0 ? 0.18 : 0.26, ease: 'easeOut' })
  }, [glow, trackable])

  const track = (event: PointerEvent<HTMLSpanElement>) => {
    if (!trackable) return
    const node = shiftRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    node.style.setProperty('--mx', ((event.clientX - rect.left) / rect.width * 100).toFixed(2) + '%')
    node.style.setProperty('--my', ((event.clientY - rect.top) / rect.height * 100).toFixed(2) + '%')
  }

  useEffect(() => () => { glow.stop() }, [glow])

  return (
    <span
      ref={shiftRef}
      className="lg-shift"
      onPointerEnter={(event) => { track(event); fadeGlow(GLOW_MAX) }}
      onPointerMove={track}
      onPointerLeave={() => fadeGlow(0)}
    >
      <span
        aria-hidden="true"
        className="lg-face"
        style={{
          background: tint ?? 'var(--lg-face-tint)',
          backdropFilter: `blur(${blur}px) saturate(1.7) brightness(0.97)`,
          WebkitBackdropFilter: `blur(${blur}px) saturate(1.7) brightness(0.97)`,
        }}
      >
        <span className="lg-top" />
        <motion.span className="lg-glow" style={{ opacity: glow }} />
      </span>
      {children}
      {overlay}
    </span>
  )
}

export interface GlassContentProps {
  title: string
  subtitle?: string
  icon?: ReactNode
  /** 右侧信息位；默认是 14px 箭头。 */
  meta?: ReactNode
  unread?: boolean
}

/** 玻璃里的内容排版：38px 图标块 + 标题/副标题 + 右侧信息位。 */
export function GlassContent({ title, subtitle, icon, meta, unread = false }: GlassContentProps) {
  return (
    <span className="lg-content">
      <span className="lg-glyph" aria-hidden="true">
        {icon ?? <MessageSquareText size={17} strokeWidth={1.7} />}
        {unread && <span className="lg-unread" />}
      </span>
      <span className="lg-text">
        <span className="lg-title" title={title}>{title}</span>
        {subtitle && <span className="lg-subtitle">{subtitle}</span>}
      </span>
      <span className="lg-meta" aria-hidden={meta === undefined ? 'true' : undefined}>
        {meta ?? <ArrowRight size={14} strokeWidth={1.8} />}
      </span>
    </span>
  )
}

export interface LiquidGlassButtonProps {
  title?: string
  subtitle?: string
  onClick?: () => void
  className?: string
  blur?: number
  tint?: string
  bounce?: number
  highlight?: boolean
  /** 内容图标；不传时用消息图标。 */
  icon?: ReactNode
  meta?: ReactNode
  unread?: boolean
  /** 当前选中项：玻璃边缘换成航线色，并带上 aria-current。 */
  active?: boolean
  ariaLabel?: string
  /** 替换默认内容排版（窄栏里的聊天记录行用它排两行文字）。 */
  children?: ReactNode
}

export function LiquidGlassButton({
  title, subtitle, onClick, className = '', blur = DEFAULT_BLUR, tint,
  bounce = DEFAULT_BOUNCE, highlight = true, icon, meta, unread, active = false, ariaLabel, children,
}: LiquidGlassButtonProps) {
  const reduced = useReducedMotion() === true
  const press = useMotionValue(0)
  const hover = useMotionValue(0)
  const pressed = useRef(false)
  const pressAnim = useRef<AnimationPlaybackControls | null>(null)
  const liftAnim = useRef<AnimationPlaybackControls | null>(null)

  const scaleX = useTransform<number, number>([press, hover], (values) =>
    (1 + PRESS_SPREAD * values[0]) * (1 + (HOVER_SCALE - 1) * values[1]))
  const scaleY = useTransform<number, number>([press, hover], (values) =>
    (1 - PRESS_SQUASH * values[0]) * (1 + (HOVER_SCALE - 1) * values[1]))
  const lift = useTransform(hover, (value) => -HOVER_LIFT * value)

  const pressDown = useCallback(() => {
    if (reduced || motionOff() || pressed.current) return
    pressed.current = true
    pressAnim.current?.stop()
    pressAnim.current = animate(press, 1, PRESS_SPRING)
  }, [press, reduced])

  const pressUp = useCallback(() => {
    if (!pressed.current) return
    pressed.current = false
    pressAnim.current?.stop()
    if (reduced || motionOff()) {
      press.set(0)
      return
    }
    pressAnim.current = animate(press, 0, {
      type: 'spring', stiffness: RELEASE_STIFFNESS, damping: releaseDamping(bounce), mass: RELEASE_MASS,
    })
  }, [bounce, press, reduced])

  const hoverIn = (event: PointerEvent<HTMLButtonElement>) => {
    if (reduced || motionOff() || event.pointerType === 'touch') return
    liftAnim.current?.stop()
    liftAnim.current = animate(hover, 1, { duration: 0.16, ease: [0.22, 0.75, 0.25, 1] })
  }

  const hoverOut = () => {
    pressUp()
    if (reduced || motionOff()) {
      hover.set(0)
      return
    }
    liftAnim.current?.stop()
    liftAnim.current = animate(hover, 0, { duration: 0.18, ease: 'easeOut' })
  }

  const keyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== ' ' || event.repeat) return
    pressDown()
  }

  const keyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === ' ') pressUp()
  }

  useEffect(() => () => {
    pressAnim.current?.stop()
    liftAnim.current?.stop()
  }, [])

  const layout = {
    '--lg-width': `${WIDTH}px`,
    '--lg-height': `${HEIGHT}px`,
    '--lg-radius': `${RADIUS}px`,
  } as CSSProperties

  return (
    <motion.button
      type="button"
      className={'lg-button ' + className}
      aria-label={ariaLabel}
      aria-current={active ? 'true' : undefined}
      data-active={active ? 'true' : undefined}
      onClick={onClick}
      onPointerDown={(event) => { if (event.button === 0) pressDown() }}
      onPointerUp={pressUp}
      onPointerCancel={pressUp}
      onPointerLeave={hoverOut}
      onPointerEnter={hoverIn}
      onKeyDown={keyDown}
      onKeyUp={keyUp}
      onBlur={pressUp}
      style={{ ...layout, scaleX, scaleY, y: lift } as MotionStyle}
    >
      <GlassSurface blur={blur} tint={tint} highlight={highlight && !reduced}>
        {children ?? (
          <GlassContent title={title ?? ''} subtitle={subtitle} icon={icon} meta={meta} unread={unread} />
        )}
      </GlassSurface>
    </motion.button>
  )
}

export default LiquidGlassButton