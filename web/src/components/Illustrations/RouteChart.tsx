import { useId } from 'react'
import { ArrowUpRight } from 'lucide-react'

// An original topographic plate, not a basemap or a calculated itinerary.
const shore = 'M0 0H310Q312 18 296 32T282 55Q300 73 302 58L322 50Q341 41 337 61L323 78 315 91Q335 96 353 82L371 74 389 84Q372 107 347 111L323 114Q320 130 334 139L350 150 355 168 381 180 382 191 405 210Q429 223 419 242L393 248 382 261Q388 275 405 271L433 264Q443 279 435 305H0Z'
const ridge = 'M-72 23C-28 13-17 56 19 49S54 11 84 19 93 60 123 64 161 48 179 77 145 115 147 139 190 165 187 192 151 209 127 217 102 248 73 243 33 222 2 235-38 268-69 251'
const shelf = 'M367-15Q342 10 354 24T390 49Q415 62 408 82T367 115Q338 131 362 146T393 167Q392 179 415 192T453 224Q466 257 441 269T439 320'
const route = 'M103 83C144 83 171 99 180 123S195 176 229 181L263 185C296 189 300 214 331 219L357 222'

export function RouteChart() {
  const id = useId().replace(/:/g, '')
  const ref = (part: string) => 'url(#' + id + part + ')'
  return <figure className="atlas-plate" aria-label="北京至上海的示例航图，非实时路线">
    <div className="plate-overline" aria-hidden="true"><span><i /> 城际航图</span><span>图版 / 01</span></div>
    <svg className="plate-map" viewBox="0 0 480 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <clipPath id={id + 'land'}><path d={shore} /></clipPath>
        <pattern id={id + 'grid'} width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M40 0H0V40" fill="none" stroke="var(--chart-grid)" strokeWidth=".8" />
          <path d="M17.5 20h5M20 17.5v5" stroke="var(--chart-grid)" strokeWidth=".65" />
        </pattern>
        <pattern id={id + 'sea'} width="8" height="8" patternUnits="userSpaceOnUse">
          <path d="m-2 2 4-4m-2 10 8-8m-2 10 4-4" stroke="var(--chart-sea-line)" strokeWidth=".8" />
        </pattern>
        <path id={id + 'ridge'} d={ridge} />
        <path id={id + 'shelf'} d={shelf} />
      </defs>
      <rect width="480" height="300" fill="var(--chart-sea)" />
      <rect width="480" height="300" fill={ref('sea')} />
      <g fill="none" stroke="var(--chart-coast)" strokeWidth=".85">
        {[0, 1, 2, 3, 4].map(i => <use key={i} href={'#' + id + 'shelf'} transform={'translate(' + i * 8 + ' ' + i * 1.2 + ')'} />)}
      </g>
      <path d={shore} fill="var(--chart-land)" stroke="var(--chart-coast)" strokeWidth="1.4" />
      <g clipPath={ref('land')}>
        <path d={ridge + 'Z'} fill="var(--chart-hill)" />
        <g fill="none" stroke="var(--chart-contour)" strokeWidth="1">
          {Array.from({ length: 18 }, (_, i) => <use key={i} href={'#' + id + 'ridge'}
            transform={'translate(' + (19 - i * 5.4) + ' ' + (i * 2.3 - 44) + ')'} />)}
          <g transform="translate(447 341) rotate(155)">
            {Array.from({ length: 10 }, (_, i) => <use key={i} href={'#' + id + 'ridge'} transform={'translate(' + (i * 7) + ' ' + (i * 2) + ')'} />)}
          </g>
        </g>
        <path d="M-20 262Q42 274 78 254T146 246Q177 262 204 243T252 229Q276 248 304 233T367 238 429 224" fill="none" stroke="var(--chart-coast)" strokeWidth="2.3" />
        <path d="m127 0 30 55 46 18 18 48 50 25-8 41 25 24 6 62m-166-74 45-34 32 6 54-25" fill="none" stroke="var(--chart-contour)" strokeDasharray="3 4" />
      </g>
      <rect width="480" height="300" fill={ref('grid')} />
      <g className="plate-route" fill="none" strokeLinecap="round" strokeLinejoin="round">
        <path d={route} stroke="var(--chart-land)" strokeWidth="7" />
        <path d={route} stroke="var(--chart-route)" strokeWidth="3.4" />
        <circle cx="103" cy="83" r="12" stroke="var(--chart-route)" opacity=".45" />
        <circle cx="103" cy="83" r="6" fill="var(--chart-route)" stroke="var(--chart-land)" strokeWidth="2.5" />
        <circle cx="357" cy="222" r="12" stroke="var(--chart-stamp)" opacity=".5" />
        <circle cx="357" cy="222" r="6" fill="var(--chart-stamp)" stroke="var(--chart-land)" strokeWidth="2.5" />
        <g transform="translate(233 181) rotate(12)"><path d="m-8-6 16 6-16 6 4-6Z" stroke="var(--chart-land)" strokeWidth="2" fill="var(--chart-route)" /></g>
      </g>
      <g className="plate-map-label">
        <text x="102" y="60" textAnchor="middle">北京</text>
        <text x="355" y="204" textAnchor="middle">上海</text>
      </g>
      <g transform="translate(446 36)" fill="var(--chart-ink)"><text y="-6" textAnchor="middle" fontSize="10">N</text>
        <path d="m0 0-5 17 5-4 5 4Z" /><path d="M0 2v10l3.2 2.5Z" fill="var(--chart-land)" /></g>
    </svg>
    <svg className="plate-strip" viewBox="0 0 340 70" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <rect width="340" height="70" fill="var(--chart-land)" />
      <g fill="none" stroke="var(--chart-contour)" strokeWidth="1">
        {[0,1,2,3,4,5,6,7].map(i => <path key={i} transform={'translate(' + (4*i) + ' ' + (-3*i) + ')'}
          d="M-10 66Q31 44 57 56T106 61Q134 47 152 52T198 63M195 4Q227 0 241 20T283 38 331 36 370 54" />)}
      </g>
      <rect width="340" height="70" fill={ref('grid')} />
      <path d="M51 43C91 43 111 23 151 29S210 48 249 34L287 24" fill="none" stroke="var(--chart-route)" strokeWidth="2.3" />
      <circle cx="51" cy="43" r="4.6" fill="var(--chart-route)" /><circle cx="287" cy="24" r="4.6" fill="var(--chart-stamp)" />
      <g className="plate-map-label"><text x="35" y="32">北京</text><text x="276" y="46">上海</text></g>
    </svg>
    <figcaption><span><ArrowUpRight size={15} aria-hidden="true" /> 北京 <b aria-hidden="true">→</b> 上海</span><span>路线示意 · 非实时导航</span></figcaption>
  </figure>
}
