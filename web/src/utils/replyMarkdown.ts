/** Normalize legacy plain-text bullet lines without touching Markdown code blocks. */
export function normalizeReplyMarkdown(value: string) {
  const lines: string[] = []
  let fence: { marker: string; length: number } | undefined
  let legacyList = false
  for (const line of value.split(/\r\n?|\n/)) {
    const marker = line.match(/^ {0,3}(\x60{3,}|~{3,})(.*)$/)
    if (fence) {
      if (marker && marker[1][0] === fence.marker && marker[1].length >= fence.length && !marker[2].trim()) {
        fence = undefined
      }
      lines.push(line)
      continue
    }
    const bullet = line.match(/^( {0,3})[·•][ \t]*(\S.*)$/)
    if (bullet) {
      lines.push(bullet[1] + '- ' + bullet[2])
      legacyList = true
      continue
    }
    if (legacyList && /^\S/.test(line) && !/^(?:[-+*][ \t]|\d+[.)][ \t])/.test(line)) lines.push('')
    legacyList = false
    if (marker) fence = { marker: marker[1][0], length: marker[1].length }
    lines.push(line)
  }
  return lines.join('\n')
}
