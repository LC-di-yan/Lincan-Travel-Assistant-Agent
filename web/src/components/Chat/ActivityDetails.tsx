import { useEffect, useRef, useState, useId } from 'react'
import { layoutActivity } from '../../utils/activityGraph'
import { activityStates, type ActivityView } from '../../utils/agentActivity'
import { ActivityNodes } from './ActivityNodes'
import './activity.css'

export function Dependencies({ view }: { view: ActivityView }) {
  if (!view.edges.length) return null
  return <dl className="dependency-list" aria-label="任务依赖">{view.nodes.map(n => {
    const parents = view.edges.filter(e => e.to === n.id).map(e => view.nodes.find(p => p.id === e.from)!.label)
    return parents.length ? <div key={n.id}><dt>{n.label}</dt><dd>依赖：{parents.join('、')}</dd></div> : null
  })}</dl>
}

function Diagram({ view, chart }: { view: ActivityView; chart: NonNullable<ReturnType<typeof layoutActivity>> }) {
  const svg = useRef<SVGSVGElement>(null)
  const prev = useRef(view)
  const grid = useId()
  const arrow = useId()
  useEffect(() => {
    const old = prev.current
    prev.current = view
    if (!view.live || !svg.current?.getClientRects().length || document.hidden ||
        document.documentElement.dataset.motion !== 'standard') return
    for (const path of svg.current.querySelectorAll<SVGPathElement>('.handoff')) {
      const { from, to } = path.dataset
      if (!view.started.includes(to!) || old.started.includes(to!)) continue
      const source = view.nodes.find(n => n.id === from)?.status
      if (source && ['cached','partial','success','returned'].includes(source)) path.classList.add('signalled')
    }
  }, [view])
  return <svg ref={svg} viewBox={'0 0 720 '+chart.height} className="task-map" aria-hidden="true">
    <defs><pattern id={grid} width="12" height="12" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".65" fill="var(--rule)" /></pattern>
      <marker id={arrow} markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto"><path d="M0 0 5 2.5 0 5Z" fill="var(--rule-strong)" /></marker></defs>
    <rect width="720" height={chart.height} fill={'url(#'+grid+')'} />
    {Array.from({length:chart.columns},(_,i)=><text key={i} x={18+i*(720/chart.columns)} y="13" className="map-stage">
      {String(i+1).padStart(2,'0')} / {i===0?'起始任务':'接续任务'}</text>)}
    {chart.paths.map(edge=><g key={JSON.stringify([edge.from,edge.to])}><path d={edge.d} className="task-wire" markerEnd={'url(#'+arrow+')'} />
      <path d={edge.d} data-from={edge.from} data-to={edge.to} className="handoff" pathLength="1" /></g>)}
    {chart.boxes.map(b=>{
      const n=view.nodes.find(n=>n.id===b.id)!
      const cut = Math.floor((b.width-28)/13)
      return <g key={n.id} transform={'translate('+b.x+' '+b.y+')'} className="map-station" data-state={n.status}>
        <rect width={b.width} height="39" rx="5" />
        <circle cx="12" cy="12" r={n.status === 'running' ? 4 : 3.5} />
        {n.status === 'running' && <circle cx="12" cy="12" r="6" className="station-ring" />}
        {n.status === 'partial' && <path d="M12 8.5a3.5 3.5 0 0 0 0 7Z" fill="var(--warn)" />}
        {['failed','timeout','unavailable','stopped'].includes(n.status) && <path d="m9 15 6-6" stroke="var(--warn)" strokeWidth="1.5" />}
        <text x="22" y="16">{n.label.length>cut?n.label.slice(0,cut-1)+'…':n.label}</text>
        <text x="22" y="32" className="map-note">{activityStates[n.status]}</text></g>
    })}
  </svg>
}

export default function ActivityDetails({ view, compact }: { view: ActivityView; compact: boolean }) {
  const chart = compact ? null : layoutActivity(view)
  const [list, setList] = useState(false)
  const graphical = !!chart && !list
  return <div className="run-details">
    <div className="run-key"><span>{graphical ? '协作航线' : '任务清单'}</span>
      {chart && <button type="button" onClick={()=>setList(!list)}>{list?'查看航线图':'查看文字清单'}</button>}</div>
    {graphical && <Diagram chart={chart} view={view} />}
    <div className={graphical ? 'sr-only' : undefined}><ActivityNodes nodes={view.nodes} /><Dependencies view={view} /></div>
  </div>
}
