'use client'

/**
 * SkeletonShimmer —— 骨架屏流光。
 *
 * 卡片固定 8 块：媒体 96、标题 16、正文 3 行 14（行距 8）、页脚 28 头像 + 12/10 两行（行距 4）；
 * 卡片 16 圆角、12 内边距、1px 边框，四组间距统一 12——边框盒正好 260px。
 * 每块用 ::after 画一条 200% 宽的高光带，1400ms linear 从 200% 0 扫到 -200% 0，
 * 第 i 块延迟 i × 90ms（0 → 630ms），只动 background-position，盒子尺寸全程不变。
 *
 * tone 切换明暗两套 alpha：dark 块 0.06 / 高光 sheen；light 块 0.09 / 高光 sheen × 2。
 * 外层 role="status" + aria-busy + aria-live 暴露加载状态，骨架块对辅助技术隐藏；
 * 数据到达后由父级整棵卸载，不做假淡出。样式与 keyframes 都写进组件内的 scoped <style>，
 * 不碰全局 CSS；卸载时 <style> 随节点一起移除，没有计时器与全局监听。
 */

import type { CSSProperties } from 'react'

const BLOCK_COUNT = 8
const MEDIA_HEIGHT = 96
const TITLE_HEIGHT = 16
const BODY_LINE_HEIGHT = 14
const BODY_LINE_GAP = 8
const BODY_WIDTHS = [100, 92, 68] as const
const FOOTER_HEIGHT = 28
const AVATAR_SIZE = 28
const FOOTER_LINE_HEIGHTS = [12, 10] as const
const FOOTER_LINE_GAP = 4
const FOOTER_LINE_WIDTH = 72
const CARD_RADIUS = 16
const CARD_PADDING = 12
const BLOCK_RADIUS = 6
const MEDIA_RADIUS = 10
const GAP = 12
const DEFAULT_DURATION = 1400
const DEFAULT_STAGGER = 90
const DEFAULT_SHEEN = 0.08
const DARK_BLOCK = 'rgb(255 255 255 / 0.06)'
const LIGHT_BLOCK = 'rgb(9 11 16 / 0.09)'
const DARK_BORDER = 'rgb(255 255 255 / 0.08)'
const LIGHT_BORDER = 'rgb(9 11 16 / 0.08)'

const CSS = `
.aligo-sk{position:relative;display:block;width:100%}
.aligo-sk__label{position:absolute;width:1px;height:1px;margin:-1px;padding:0;border:0;overflow:hidden;white-space:nowrap;clip-path:inset(50%)}
.aligo-sk__stack{display:grid;gap:${GAP}px}
.aligo-sk__card{display:flex;flex-direction:column;gap:${GAP}px;box-sizing:border-box;padding:${CARD_PADDING}px;border:1px solid var(--sk-border);border-radius:var(--sk-card-radius,${CARD_RADIUS}px)}
.aligo-sk__block{position:relative;display:block;flex:none;overflow:hidden;border-radius:${BLOCK_RADIUS}px;background:var(--sk-block)}
.aligo-sk__block::after{content:"";position:absolute;inset:0;pointer-events:none;
background-image:linear-gradient(90deg,transparent 0%,rgba(255,255,255,var(--sk-sheen)) 50%,transparent 100%);
background-size:200% 100%;background-repeat:no-repeat;background-position:200% 0;
animation:aligo-sk-sheen var(--sk-duration,${DEFAULT_DURATION}ms) linear infinite;
animation-delay:var(--sk-delay,0ms);animation-fill-mode:both}
.aligo-sk__block--media{height:${MEDIA_HEIGHT}px;width:100%;border-radius:${MEDIA_RADIUS}px}
.aligo-sk__block--title{height:${TITLE_HEIGHT}px;width:62%}
.aligo-sk__body{display:flex;flex-direction:column;gap:${BODY_LINE_GAP}px}
.aligo-sk__line{height:${BODY_LINE_HEIGHT}px}
.aligo-sk__footer{display:flex;align-items:center;gap:10px;height:${FOOTER_HEIGHT}px}
.aligo-sk__avatar{width:${AVATAR_SIZE}px;height:${AVATAR_SIZE}px;border-radius:50%}
.aligo-sk__footer-lines{display:flex;flex:1;min-width:0;flex-direction:column;gap:${FOOTER_LINE_GAP}px}
.aligo-sk__line--footer{height:${FOOTER_LINE_HEIGHTS[0]}px}
.aligo-sk__line--footer-sm{height:${FOOTER_LINE_HEIGHTS[1]}px;width:${FOOTER_LINE_WIDTH}%}
@keyframes aligo-sk-sheen{from{background-position:200% 0}to{background-position:-200% 0}}
@media (prefers-reduced-motion: reduce){.aligo-sk__block::after{animation:none !important;opacity:0 !important}}
:root:not([data-motion='standard'])[data-motion] .aligo-sk__block::after{animation:none !important;opacity:0 !important}
`

function detectTone(): 'dark' | 'light' {
  if (typeof document === 'undefined') return 'dark'
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

export interface SkeletonShimmerProps {
  /** 单次扫光时长，毫秒。 */
  duration?: number
  /** 相邻两块起扫的间隔，毫秒。 */
  stagger?: number
  /** dark 的高光 alpha；light 自动 ×2。 */
  sheen?: number
  /** 卡片圆角；块圆角固定 6、媒体 10。 */
  radius?: number
  /** 明暗两套 alpha；auto 读取 html.dark。 */
  tone?: 'light' | 'dark' | 'auto'
  /** 视觉隐藏的加载文案。 */
  label?: string
  /** 同屏放置几张同样的卡（每张仍是 8 块）。 */
  count?: number
}

export function SkeletonShimmer({
  duration = DEFAULT_DURATION,
  stagger = DEFAULT_STAGGER,
  sheen = DEFAULT_SHEEN,
  radius = CARD_RADIUS,
  tone = 'auto',
  label = '加载中',
  count = 1,
}: SkeletonShimmerProps) {
  const resolved = tone === 'auto' ? detectTone() : tone
  const dark = resolved === 'dark'
  const scope = {
    '--sk-duration': `${duration}ms`,
    '--sk-block': dark ? DARK_BLOCK : LIGHT_BLOCK,
    '--sk-sheen': String(dark ? sheen : sheen * 2),
    '--sk-border': dark ? DARK_BORDER : LIGHT_BORDER,
    '--sk-card-radius': `${radius}px`,
  } as CSSProperties
  const delay = (index: number) => ({ '--sk-delay': `${index * stagger}ms` }) as CSSProperties
  const cards = Math.max(1, Math.floor(count))

  return (
    <div className="aligo-sk" data-tone={resolved} role="status" aria-busy="true" aria-live="polite" style={scope}>
      <style data-aligo-skeleton="">{CSS}</style>
      <span className="aligo-sk__label">{label}</span>
      <div className="aligo-sk__stack">
        {Array.from({ length: cards }, (_, card) => (
          <div key={card} className="aligo-sk__card" aria-hidden="true" data-blocks={BLOCK_COUNT}>
            <span className="aligo-sk__block aligo-sk__block--media" style={delay(0)} aria-hidden="true" />
            <span className="aligo-sk__block aligo-sk__block--title" style={delay(1)} aria-hidden="true" />
            <span className="aligo-sk__body">
              {BODY_WIDTHS.map((width, line) => (
                <span key={line} className="aligo-sk__block aligo-sk__line"
                  style={{ ...delay(2 + line), width: `${width}%` }} aria-hidden="true" />
              ))}
            </span>
            <span className="aligo-sk__footer">
              <span className="aligo-sk__block aligo-sk__avatar" style={delay(5)} aria-hidden="true" />
              <span className="aligo-sk__footer-lines">
                <span className="aligo-sk__block aligo-sk__line aligo-sk__line--footer" style={delay(6)} aria-hidden="true" />
                <span className="aligo-sk__block aligo-sk__line aligo-sk__line--footer-sm" style={delay(7)} aria-hidden="true" />
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default SkeletonShimmer