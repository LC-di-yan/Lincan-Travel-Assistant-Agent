/**
 * themeRevealCore —— 圆形主题揭示的浏览器侧核心。
 *
 * 只负责动画：新主题以圆形 clip-path 从起点扩散（默认 350ms / ease-out），
 * 动画作用在 ::view-transition-new(root) 的快照上，圆之外的旧画面保持静止。
 * 主题本身由调用方在 apply 里提交（例如本项目 hooks/useTheme.ts 的 .dark 类）。
 * 浏览器不支持 View Transitions 时直接 apply（可选 120ms 淡入）；
 * prefers-reduced-motion: reduce 或 data-motion 减弱策略时一帧内到达最终状态。
 */

import { flushSync } from 'react-dom'

export const REVEAL_DURATION = 350
export const MIN_DURATION = 200
export const MAX_DURATION = 700
export const REVEAL_EASING = 'ease-out'
export const FALLBACK_FADE_DURATION = 120
export const FALLBACK_FADE_FROM = 0.55
export const FOCUS_RING = '2px'

const ROOT_STYLE_FLAG = 'data-theme-reveal-base'
const NAME_STYLE_FLAG = 'data-theme-reveal-name'

/** 快照盒：<html> 用视口，其它目标用它自己的 rect；起点坐标一律换算到盒内。 */
interface SnapshotBox {
  left: number
  top: number
  width: number
  height: number
}

/** 触发事件的最小形状：React 的 MouseEvent 结构上即满足。 */
export interface ThemeTriggerEvent {
  clientX: number
  clientY: number
  detail: number
  currentTarget?: HTMLElement | null
}

export interface ThemeRevealRequest {
  /** 切换目标，默认整个文档（<html>）；传入元素时只切换该舞台。 */
  target?: HTMLElement | null
  /** 触发事件；键盘触发（detail === 0）没有坐标，圆从按钮中心开始。 */
  event?: ThemeTriggerEvent | null
  /** true 时圆从点击位置开始；false 时从目标盒中心开始。 */
  fromClick?: boolean
  /** 揭示时长，可调区间 200-700ms，默认 350ms。 */
  duration?: number
  /** 仅在浏览器没有 View Transitions 时生效的 120ms 透明度淡入。 */
  fade?: boolean
  /** 提交主题：在过渡的更新回调里同步执行（flushSync 内），此时新快照已是新主题。 */
  apply: () => void
}

export interface RevealSession {
  transition: ViewTransition | null
  animation: Animation | null
  staged: HTMLElement | null
  rule: HTMLStyleElement | null
  seq: number
}

let nameSeq = 0

export function createSession(): RevealSession {
  return { transition: null, animation: null, staged: null, rule: null, seq: 0 }
}

/** 系统减弱动态，或项目自己的 data-motion 策略（reduced / static）都按减弱处理。 */
function prefersReducedMotion(): boolean {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return true
  const policy = document.documentElement.dataset.motion
  return typeof policy === 'string' && policy !== 'standard'
}

/** 过渡期间旧快照必须静止：这条规则全局只注入一次。 */
function ensureRootStyle(): void {
  if (document.querySelector('style[' + ROOT_STYLE_FLAG + ']')) return
  const style = document.createElement('style')
  style.setAttribute(ROOT_STYLE_FLAG, '')
  style.textContent =
    '::view-transition-old(root), ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }'
  document.head.appendChild(style)
}

/** 命名舞台同理：临时插一条规则，收尾时整条移除。 */
function stageNamedRule(name: string): HTMLStyleElement {
  const style = document.createElement('style')
  style.setAttribute(NAME_STYLE_FLAG, name)
  style.textContent =
    '::view-transition-old(' + name + '), ::view-transition-new(' + name + ') { animation: none; mix-blend-mode: normal; }'
  document.head.appendChild(style)
  return style
}

function clearStage(session: RevealSession): void {
  const staged = session.staged
  if (staged) {
    session.staged = null
    staged.style.removeProperty('view-transition-name')
  }
  const rule = session.rule
  if (rule) {
    session.rule = null
    rule.remove()
  }
}

/** 任何时刻只允许一个过渡：启动新过渡前、以及卸载时都走这里。 */
export function cancelSession(session: RevealSession): void {
  const running = session.transition
  if (running) {
    session.transition = null
    try {
      running.skipTransition()
    } catch {
      /* 过渡已收尾 */
    }
  }
  const anim = session.animation
  if (anim) {
    session.animation = null
    try {
      anim.cancel()
    } catch {
      /* 动画已收尾 */
    }
  }
  clearStage(session)
}

function snapshotBox(scope: HTMLElement): SnapshotBox {
  if (scope === document.documentElement) {
    return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight }
  }
  const rect = scope.getBoundingClientRect()
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
}

/** 圆心（盒内坐标）：点击位置 -> 按钮中心（键盘） -> 目标盒中心。 */
function revealOrigin(
  box: SnapshotBox,
  fromClick: boolean,
  event: ThemeTriggerEvent | null | undefined,
): { x: number; y: number } {
  if (!fromClick) return { x: box.width / 2, y: box.height / 2 }
  if (event && event.detail > 0) return { x: event.clientX - box.left, y: event.clientY - box.top }
  const trigger = event && event.currentTarget ? event.currentTarget.getBoundingClientRect() : null
  if (!trigger) return { x: box.width / 2, y: box.height / 2 }
  return {
    x: trigger.left + trigger.width / 2 - box.left,
    y: trigger.top + trigger.height / 2 - box.top,
  }
}

/** R = hypot(max(X, W - X), max(Y, H - Y))，保证最终圆覆盖快照盒每个角。 */
function revealRadius(box: SnapshotBox, x: number, y: number): number {
  return Math.hypot(Math.max(x, box.width - x), Math.max(y, box.height - y))
}

export function runReveal(session: RevealSession, request: ThemeRevealRequest): void {
  const scope = request.target ?? document.documentElement
  const seq = ++session.seq
  cancelSession(session)

  if (!scope.isConnected) {
    request.apply()
    return
  }

  const reduced = prefersReducedMotion()
  if (reduced || typeof document.startViewTransition !== 'function') {
    request.apply()
    if (!reduced && (request.fade ?? true)) {
      session.animation = scope.animate(
        [{ opacity: FALLBACK_FADE_FROM }, { opacity: 1 }],
        { duration: FALLBACK_FADE_DURATION, easing: REVEAL_EASING },
      )
    }
    return
  }

  ensureRootStyle()

  const isRoot = scope === document.documentElement
  const box = snapshotBox(scope)
  const origin = revealOrigin(box, request.fromClick ?? true, request.event)
  const radius = revealRadius(box, origin.x, origin.y)
  const existing = isRoot ? 'none' : getComputedStyle(scope).getPropertyValue('view-transition-name').trim()
  const named = !isRoot && (existing === '' || existing === 'none')
  const stagedName = 'theme-reveal-' + ++nameSeq

  if (named) {
    scope.style.viewTransitionName = stagedName
    session.staged = scope
    session.rule = stageNamedRule(stagedName)
  }
  const pseudo = isRoot ? 'root' : named ? stagedName : existing

  let transition: ViewTransition
  try {
    transition = document.startViewTransition(() => {
      flushSync(() => {
        request.apply()
      })
    })
  } catch {
    clearStage(session)
    request.apply()
    return
  }
  session.transition = transition

  const settle = () => {
    if (session.transition === transition) session.transition = null
    clearStage(session)
  }
  transition.finished.then(settle, settle)

  // ready 之后快照已生成，才能对 ::view-transition-new 动画 clip-path。
  transition.ready.then(
    () => {
      if (session.seq !== seq) return
      try {
        session.animation = document.documentElement.animate(
          [
            { clipPath: 'circle(0px at ' + origin.x + 'px ' + origin.y + 'px)' },
            { clipPath: 'circle(' + radius + 'px at ' + origin.x + 'px ' + origin.y + 'px)' },
          ],
          {
            duration: Math.min(MAX_DURATION, Math.max(MIN_DURATION, request.duration ?? REVEAL_DURATION)),
            easing: REVEAL_EASING,
            pseudoElement: '::view-transition-new(' + pseudo + ')',
          },
        )
      } catch {
        // 伪元素动画不可用时直接收尾，主题已经提交。
        try {
          transition.skipTransition()
        } catch {
          /* 过渡已收尾 */
        }
      }
    },
    () => {
      /* ready 之前被 skip 或 abort，主题仍按最后一次提交 */
    },
  )
}

const sharedSession = createSession()

/** 命令式入口：只做揭示动画，主题由 apply 自己提交。 */
export function revealThemeChange(request: ThemeRevealRequest): void {
  runReveal(sharedSession, request)
}

/** 中止命令式路径上仍在跑的过渡。 */
export function cancelThemeReveal(): void {
  sharedSession.seq += 1
  cancelSession(sharedSession)
}
