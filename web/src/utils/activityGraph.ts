import type { ActivityView } from './agentActivity'

// Arrange only the declared DAG. Ambiguous or unwieldy schedules remain a list.
export function layoutActivity(view: ActivityView) {
  if (!view.graphEligible || view.nodes.length > 12) return null
  const ranks = new Map<string, number>()
  const layers: string[][] = []
  while (ranks.size < view.nodes.length) {
    const layer = view.nodes.filter(n => !ranks.has(n.id) &&
      view.edges.every(e => e.to !== n.id || ranks.has(e.from))).map(n => n.id)
    if (!layer.length || layers.length >= 4 || layer.length > 6) return null
    for (const id of layer) ranks.set(id, layers.length)
    layers.push(layer)
  }
  const rows = Math.max(...layers.map(l => l.length))
  const step = 720 / layers.length, width = step - 36, height = rows * 53 + 40
  const boxes = layers.flatMap((layer, col) => layer.map((id, i) => ({
    id, col, x: col * step + 18, y: 29 + (rows - layer.length) * 26.5 + i * 53, width,
  })))
  const byId = new Map(boxes.map(b => [b.id, b]))
  const paths = view.edges.map(({ from, to }) => {
    const a = byId.get(from)!, b = byId.get(to)!
    const x = a.x + a.width, y = a.y + 19, z = b.y + 19
    const d = b.col === a.col + 1
      ? 'M'+x+' '+y+' C'+(x+19)+' '+y+' '+(b.x-19)+' '+z+' '+b.x+' '+z
      : 'M'+x+' '+y+' H'+(x+9)+' V18 H'+(b.x-10)+' V'+z+' H'+b.x
    return { from, to, d }
  })
  return { boxes, paths, height, columns: layers.length }
}
