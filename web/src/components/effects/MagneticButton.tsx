'use client'

/**
 * MagneticButton —— 磁吸按钮。
 *
 * 指针进入按钮中心 140px 的磁场后，按钮朝指针方向最多被拉动 16px；指针离开后用同一个
 * 弹簧（刚度 260 / 阻尼 20 / 质量 1）带回原位。按钮内文字以 35% 的比例跟随形成视差；
 * 指针在磁场内时按钮背景转为纯白、文字转为纯黑，并在指针附近透出一小撮粉色光斑。
 * 按钮移动时磁场容器尺寸不变，只动画 transform 与 opacity。
 */

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { animate, motion, useMotionTemplate, useMotionValue, useReducedMotion, useTransform } from 'motion/react'

const FIELD_RADIUS = 140
const PULL_DISTANCE = 16
const SPRING_STIFFNESS = 260
const SPRING_DAMPING = 20
const SPRING_MASS = 1
const SCALE_TARGET = 1.03
const SCALE_STIFFNESS = 300
const SCALE_DAMPING = 20
const TEXT_RATIO = 0.35
const GLOW_RADIUS = 32
const GLOW_COLOR = 'rgba(255, 105, 180, 0.34)'
const TOUCH_SCALE = 0.98
const STRENGTH_POWER = 1.6

type ForwardedProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  | 'children'
  | 'onDrag'
  | 'onDragStart'
  | 'onDragEnd'
  | 'onDragEnter'
  | 'onDragLeave'
  | 'onDragOver'
  | 'onDrop'
  | 'onAnimationStart'
  | 'onAnimationEnd'
  | 'onAnimationIteration'
>

export interface MagneticButtonProps extends ForwardedProps {
  radius?: number
  pull?: number
  stiffness?: number
  damping?: number
  scale?: number
  glow?: boolean
  children?: ReactNode
  className?: string
  /** 监听指针的元素；不传时使用自带的 280×280 磁场容器。 */
  watch?: HTMLElement | null
  /** 不套规格视觉与磁场容器，外观交给 className。 */
  bare?: boolean
  [key: `data-${string}`]: string | undefined
}

export function MagneticButton({
  radius = FIELD_RADIUS,
  pull = PULL_DISTANCE,
  stiffness = SPRING_STIFFNESS,
  damping = SPRING_DAMPING,
  scale = SCALE_TARGET,
  glow = true,
  children,
  className = '',
  watch = null,
  bare = false,
  ...rest
}: MagneticButtonProps) {
  const fieldRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const [hovered, setHovered] = useState(false)
  const reduced = useReducedMotion() === true
  // 媒体查询会在运行中被系统设置或调试工具改写，事件里实时读取才不会漏掉切换。
  const motionOff = useCallback(
    () => reduced || window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [reduced],
  )

  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const zoom = useMotionValue(1)
  const glowOpacity = useMotionValue(0)
  const pointerX = useMotionValue(0)
  const pointerY = useMotionValue(0)
  const textX = useTransform(x, (value) => value * TEXT_RATIO)
  const textY = useTransform(y, (value) => value * TEXT_RATIO)
  const glowBackground = useMotionTemplate`radial-gradient(${GLOW_RADIUS}px circle at ${pointerX}px ${pointerY}px, ${GLOW_COLOR}, transparent 68%)`

  const settle = useCallback(() => {
    const spring = { type: 'spring' as const, stiffness, damping, mass: SPRING_MASS }
    animate(x, 0, spring)
    animate(y, 0, spring)
    animate(zoom, 1, { type: 'spring', stiffness: SCALE_STIFFNESS, damping: SCALE_DAMPING, mass: SPRING_MASS })
    animate(glowOpacity, 0, spring)
  }, [damping, glowOpacity, stiffness, x, y, zoom])

  useEffect(() => {
    const target = watch ?? fieldRef.current
    if (!target) return
    if (motionOff()) settle()
    const spring = { type: 'spring' as const, stiffness, damping, mass: SPRING_MASS }
    const zoomSpring = { type: 'spring' as const, stiffness: SCALE_STIFFNESS, damping: SCALE_DAMPING, mass: SPRING_MASS }

    const track = (event: PointerEvent) => {
      const button = buttonRef.current
      if (!button) return
      if (motionOff()) {
        settle()
        return
      }
      const rect = button.getBoundingClientRect()
      const centerX = rect.left + rect.width / 2 - x.get()
      const centerY = rect.top + rect.height / 2 - y.get()
      const offsetX = event.clientX - centerX
      const offsetY = event.clientY - centerY
      const distance = Math.hypot(offsetX, offsetY)
      pointerX.set(event.clientX - (rect.left - x.get()))
      pointerY.set(event.clientY - (rect.top - y.get()))
      if (distance === 0 || distance >= radius) {
        animate(x, 0, spring)
        animate(y, 0, spring)
        return
      }
      const strength = Math.pow(1 - Math.min(distance / radius, 1), STRENGTH_POWER)
      animate(x, (offsetX / distance) * strength * pull, spring)
      animate(y, (offsetY / distance) * strength * pull, spring)
    }

    const onEnter = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') setHovered(true)
      if (event.pointerType === 'touch' || motionOff()) return
      animate(zoom, scale, zoomSpring)
      animate(glowOpacity, 1, spring)
      track(event)
    }
    const onMove = (event: PointerEvent) => {
      if (motionOff()) {
        settle()
        return
      }
      if (event.pointerType === 'touch') return
      track(event)
    }
    const onLeave = () => {
      setHovered(false)
      settle()
    }

    target.addEventListener('pointerenter', onEnter)
    target.addEventListener('pointermove', onMove)
    target.addEventListener('pointerleave', onLeave)
    return () => {
      target.removeEventListener('pointerenter', onEnter)
      target.removeEventListener('pointermove', onMove)
      target.removeEventListener('pointerleave', onLeave)
      x.stop()
      y.stop()
      zoom.stop()
      glowOpacity.stop()
    }
  }, [damping, glowOpacity, motionOff, pointerX, pointerY, pull, radius, scale, settle, stiffness, watch, x, y, zoom])

  useEffect(() => {
    const element = fieldRef.current ?? buttonRef.current
    if (!element) return
    const stopX = pointerX.on('change', (value) => element.style.setProperty('--mx', value + 'px'))
    const stopY = pointerY.on('change', (value) => element.style.setProperty('--my', value + 'px'))
    return () => { stopX(); stopY() }
  }, [pointerX, pointerY, bare])

  const press = (event: ReactPointerEvent<HTMLButtonElement>) => {
    rest.onPointerDown?.(event)
    if (motionOff() || event.pointerType !== 'touch') return
    animate(zoom, TOUCH_SCALE, { type: 'spring', stiffness: SCALE_STIFFNESS, damping: SCALE_DAMPING, mass: SPRING_MASS })
  }
  const release = (event: ReactPointerEvent<HTMLButtonElement>) => {
    rest.onPointerUp?.(event)
    if (motionOff()) return
    animate(zoom, 1, { type: 'spring', stiffness: SCALE_STIFFNESS, damping: SCALE_DAMPING, mass: SPRING_MASS })
  }
  const cancelPress = (event: ReactPointerEvent<HTMLButtonElement>) => {
    rest.onPointerCancel?.(event)
    if (motionOff()) return
    animate(zoom, 1, { type: 'spring', stiffness: SCALE_STIFFNESS, damping: SCALE_DAMPING, mass: SPRING_MASS })
  }

  const visual = bare
    ? 'relative '
    : 'relative h-[56px] rounded-full border border-transparent px-[32px] bg-[#F2F0E9] text-[16px] font-medium tracking-[-0.01em] text-[#0B0C0E] cursor-pointer ' +
      'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-[#C9F45A] '

  const button = (
    <motion.button
      ref={buttonRef}
      style={{
        x,
        y,
        scale: zoom,
        backgroundColor: hovered ? '#FFFFFF' : undefined,
        color: hovered ? '#000000' : undefined,
        borderColor: hovered ? '#000000' : undefined,
      }}
      onPointerDown={press}
      onPointerUp={release}
      onPointerCancel={cancelPress}
      className={visual + className}
      {...rest}
      type={rest.type ?? 'button'}
    >
      {glow && (
        <motion.span
          aria-hidden="true"
          style={{ background: glowBackground, opacity: glowOpacity }}
          className="pointer-events-none absolute inset-0 rounded-full"
        />
      )}
      <motion.span style={{ x: textX, y: textY }} className="relative inline-flex items-center justify-center gap-[10px]">
        {children}
      </motion.span>
    </motion.button>
  )

  if (bare) return button
  return (
    <div ref={fieldRef} className="relative flex h-[280px] w-[280px] items-center justify-center">
      {button}
    </div>
  )
}

export default MagneticButton
