'use client'

/**
 * ThemeReveal —— 圆形主题揭示按钮（自包含用法）。
 *
 * 自带按钮，点击后把主题写进目标元素的 data-theme（默认 <html>）与 localStorage 的 theme-reveal，
 * 新主题以圆形 clip-path 从点击位置扩散（350ms / ease-out），旧画面在圆外保持静止。
 * 动画核心在 ./themeRevealCore.ts；项目已有主题实现时可改用那里的 revealThemeChange。
 */

import { useEffect, useState, type MouseEvent, type ReactNode } from 'react'
import {
  FOCUS_RING,
  REVEAL_DURATION,
  cancelSession,
  createSession,
  runReveal,
} from './themeRevealCore'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'theme-reveal'

export interface ThemeRevealProps {
  /** 切换目标，默认整个文档（<html>）；传入元素时只切换该舞台。 */
  target?: HTMLElement | null
  /** true 时圆从点击位置开始（键盘触发退化为按钮中心）；false 时从目标盒中心开始。 */
  fromClick?: boolean
  /** 揭示时长，可调区间 200-700ms，默认 350ms。 */
  duration?: number
  /** 仅在浏览器没有 View Transitions 时生效的 120ms 透明度淡入。 */
  fade?: boolean
  /** 按钮可见文字。 */
  label?: string
  /** 主题提交回调，与 data-theme 写在同一个回调里。 */
  onThemeChange?: (theme: Theme) => void
  children?: ReactNode
}

let instanceSeq = 0

function readTheme(scope: HTMLElement): Theme {
  const attr = scope.getAttribute('data-theme')
  if (attr === 'dark' || attr === 'light') return attr
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    /* 存储不可用时退回系统偏好 */
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** 唯一的 DOM 提交点：data-theme、localStorage、外部回调在这里一次写完。 */
function commitTheme(scope: HTMLElement, theme: Theme, onThemeChange?: (theme: Theme) => void): void {
  scope.setAttribute('data-theme', theme)
  if (scope === document.documentElement) {
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* 存储不可用时只保留本次会话的主题 */
    }
  }
  onThemeChange?.(theme)
}

export function ThemeReveal({
  target = null,
  fromClick = true,
  duration = REVEAL_DURATION,
  fade = true,
  label = '切换主题',
  onThemeChange,
  children,
}: ThemeRevealProps) {
  const [session] = useState(createSession)
  const [revealName] = useState(() => 'theme-reveal-' + ++instanceSeq)
  const [styleName] = useState(() => 'theme-reveal-trigger-' + ++instanceSeq)

  useEffect(() => {
    return () => {
      session.seq += 1
      cancelSession(session)
    }
  }, [session])

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    const scope = target ?? document.documentElement
    const next: Theme = readTheme(scope) === 'dark' ? 'light' : 'dark'
    runReveal(session, {
      target: scope,
      event: {
        clientX: event.clientX,
        clientY: event.clientY,
        detail: event.detail,
        currentTarget: event.currentTarget,
      },
      fromClick,
      duration,
      fade,
      apply: () => commitTheme(scope, next, onThemeChange),
    })
  }

  const css =
    '.' + styleName + ' {\n' +
    '  font: inherit;\n' +
    '  color: inherit;\n' +
    '  background: transparent;\n' +
    '  border: 1px solid currentColor;\n' +
    '  border-radius: 999px;\n' +
    '  padding: 0.45rem 0.9rem;\n' +
    '  cursor: pointer;\n' +
    '}\n' +
    '.' + styleName + ':focus-visible {\n' +
    '  outline: ' + FOCUS_RING + ' solid currentColor;\n' +
    '  outline-offset: 2px;\n' +
    '}\n' +
    '::view-transition-old(root),\n' +
    '::view-transition-new(root) {\n' +
    '  animation: none;\n' +
    '  mix-blend-mode: normal;\n' +
    '}\n' +
    '::view-transition-old(' + revealName + '),\n' +
    '::view-transition-new(' + revealName + ') {\n' +
    '  animation: none;\n' +
    '  mix-blend-mode: normal;\n' +
    '}\n'

  return (
    <>
      <style>{css}</style>
      <button type="button" className={styleName} onClick={handleClick}>
        {children ?? label}
      </button>
    </>
  )
}

export default ThemeReveal
