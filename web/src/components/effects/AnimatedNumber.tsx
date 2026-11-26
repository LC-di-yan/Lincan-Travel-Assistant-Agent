'use client'

/**
 * AnimatedNumber —— 数字滚动。
 *
 * 目标值变化时用 420ms 的 requestAnimationFrame 补间，从当前显示值数到新值；
 * 进度由手写的 cubic-bezier(0.2, 0.8, 0.2, 1) 求值（Newton-Raphson 解 x → t，再取 y）。
 * 补间中途换目标时从当前显示值改道并重新计满 420ms；最后一帧精确写入目标值；
 * NaN / ±Infinity 原样透传；prefers-reduced-motion 时直接落终值，不启动 rAF。
 */

import { useEffect, useRef, useState } from 'react'

const DURATION = 420
const PRECISION = 0
const X1 = 0.2
const Y1 = 0.8
const X2 = 0.2
const Y2 = 1
const NEWTON_ITERATIONS = 6
const NEWTON_EPSILON = 0.000001

export interface AnimatedNumberOptions {
  duration?: number
  precision?: number
  separators?: boolean
}

export interface AnimatedNumberProps {
  value: number
  duration?: number
  precision?: number
  separators?: boolean
  className?: string
}

const sampleCurve = (time: number, first: number, second: number) => {
  const inverse = 1 - time
  return 3 * inverse * inverse * time * first + 3 * inverse * time * time * second + time * time * time
}

const sampleSlope = (time: number, first: number, second: number) => {
  const inverse = 1 - time
  return 3 * inverse * inverse * first + 6 * inverse * time * (second - first) + 3 * time * time * (1 - second)
}

const solveTime = (progress: number) => {
  let time = progress
  for (let index = 0; index < NEWTON_ITERATIONS; index += 1) {
    const error = sampleCurve(time, X1, X2) - progress
    if (Math.abs(error) < NEWTON_EPSILON) return time
    const slope = sampleSlope(time, X1, X2)
    if (slope === 0) break
    time -= error / slope
  }
  return time < 0 ? 0 : time > 1 ? 1 : time
}

const ease = (progress: number) => {
  if (progress <= 0) return 0
  if (progress >= 1) return 1
  return sampleCurve(solveTime(progress), Y1, Y2)
}

const groupThousands = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')

const format = (value: number, precision: number, separators: boolean) => {
  if (!Number.isFinite(value)) return String(value)
  const fixed = value.toFixed(precision)
  if (!separators) return fixed
  const negative = fixed.startsWith('-')
  const body = negative ? fixed.slice(1) : fixed
  const [integer, fraction] = body.split('.')
  const grouped = groupThousands(integer)
  return (negative ? '-' : '') + grouped + (fraction === undefined ? '' : '.' + fraction)
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

// 规格要求 hook 与组件同文件导出；这条规则只针对 HMR 边界，这里按需放行。
// eslint-disable-next-line react-refresh/only-export-components
export function useAnimatedNumber(target: number, options: AnimatedNumberOptions = {}): string {
  const duration = options.duration ?? DURATION
  const precision = options.precision ?? PRECISION
  const separators = options.separators ?? true

  const [display, setDisplay] = useState(() => format(target, precision, separators))
  const shownRef = useRef(Number.isFinite(target) ? target : 0)
  const startRef = useRef(0)
  const frameRef = useRef<number | null>(null)
  const mountedRef = useRef(true)
  const initialRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [])

  useEffect(() => {
    if (initialRef.current) {
      initialRef.current = false
      shownRef.current = Number.isFinite(target) ? target : 0
      return
    }
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
    if (!Number.isFinite(target) || prefersReducedMotion()) {
      shownRef.current = Number.isFinite(target) ? target : 0
      const settled = format(target, precision, separators)
      queueMicrotask(() => {
        if (mountedRef.current) setDisplay(settled)
      })
      return
    }
    const from = Number.isFinite(shownRef.current) ? shownRef.current : 0
    const to = target
    startRef.current = 0
    const step = (now: number) => {
      if (!mountedRef.current) return
      if (startRef.current === 0) startRef.current = now
      const progress = duration <= 0 ? 1 : Math.min(1, (now - startRef.current) / duration)
      if (progress >= 1) {
        shownRef.current = to
        frameRef.current = null
        setDisplay(format(to, precision, separators))
        return
      }
      const value = from + (to - from) * ease(progress)
      shownRef.current = value
      setDisplay(format(value, precision, separators))
      frameRef.current = requestAnimationFrame(step)
    }
    frameRef.current = requestAnimationFrame(step)
  }, [duration, precision, separators, target])

  return display
}

export function AnimatedNumber({
  value,
  duration,
  precision = PRECISION,
  separators = true,
  className = 'min-w-[9ch] text-right',
}: AnimatedNumberProps) {
  const text = useAnimatedNumber(value, { duration, precision, separators })
  return (
    <span
      className={'inline-block ' + className}
      style={{ fontVariantNumeric: 'tabular-nums' }}
    >
      {text}
    </span>
  )
}

export default AnimatedNumber
