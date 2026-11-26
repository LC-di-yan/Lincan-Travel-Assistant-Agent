import { useState } from 'react'
import { CalendarRange, BookOpenCheck, TrainFront, ReceiptText, CloudSun, Coins, Heart, History, ChevronDown } from 'lucide-react'
import { LiquidGlassButton } from '../effects/LiquidGlassButton'

export function BriefHeading() {
  return <div className="brief-heading">
    <p className="desk-kicker"><span aria-hidden="true" /> ALIGO <i>/</i> 差旅航图台</p>
    <h1>下一程，<em>去哪里？</em></h1>
    <p className="brief-description">写下出差的时间、地点和预算。<br />我来核对交通与住宿，帮你整理行程。</p>
  </div>
}

const examples = [
  { icon: CalendarRange, label: '规划行程', detail: '起讫、日期与预算', prompt: '明天从北京去上海出差 3 天，往返预算 2000 元，请帮我规划。' },
  { icon: BookOpenCheck, label: '查差旅政策', detail: '住宿标准与报销', prompt: '去上海出差，公司的住宿标准是多少？' },
  { icon: TrainFront, label: '查车次', detail: '出发站与到达时刻', prompt: '查明天上午从北京到上海的高铁班次。' },
  { icon: ReceiptText, label: '记一笔费用', detail: '按原币记录支出', prompt: '记一笔打车费 50 元。' },
  { icon: CloudSun, label: '看天气', detail: '目的地预报', prompt: '北京明天的天气怎么样？' },
  { icon: Coins, label: '换算汇率', detail: '出行前换算', prompt: '100 美元是多少人民币？' },
  { icon: Heart, label: '设置偏好', detail: '需要时再保存', prompt: '我出差喜欢坐高铁。' },
  { icon: History, label: '查行程记录', detail: '过去的出差摘要', prompt: '查询我之前的差旅行程记录。' },
]

export function BriefExamples({ onChoose }: { onChoose: (value: string) => void }) {
  const [more, setMore] = useState(false)
  return <section className="brief-examples chart-paper" aria-labelledby="examples-title">
    <div className="example-heading">
      <h2 id="examples-title">从示例开始</h2><span>只填入，不发送</span>
      <button type="button" aria-expanded={more} onClick={() => setMore(!more)}>{more ? '收起' : '更多示例'} <ChevronDown size={14} aria-hidden="true" /></button>
    </div>
    <div className="example-grid">{examples.slice(0, more ? examples.length : 4).map(({ icon: Icon, label, prompt, detail }) =>
      <LiquidGlassButton
        key={label}
        className="lg-fill"
        title={label}
        subtitle={detail}
        icon={<Icon size={18} strokeWidth={1.7} />}
        onClick={() => onChoose(prompt)}
      />)}</div>
  </section>
}
