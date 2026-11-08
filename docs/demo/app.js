/* Aligo 静态演示：读取真实录制数据并回放渲染。数据来自 /api/chat 的真实 SSE 录制。 */
const DATA = 'data/';

const SCENES = [
  { key: 'itinerary', label: '行程规划', desc: '一句话生成 3 天行程' },
  { key: 'train', label: '火车票', desc: '12306 实时余票' },
  { key: 'rag', label: '知识库问答', desc: '树索引检索 + 出处' },
  { key: 'weather', label: '天气查询', desc: '联网搜索 + 判断' },
  { key: 'expense', label: '费用记录', desc: '自然语言记账' },
  { key: 'currency', label: '汇率换算', desc: '实时汇率' },
  { key: 'preference', label: '偏好记忆', desc: '说一次就记住' },
];

const esc = (s) => String(s == null ? '' : s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const money = (n) => Number(n || 0).toFixed(2);

/* 每个 agent 的卡片渲染器：输入该 agent 的 data，输出 HTML 字符串 */
const RENDER = {
  itinerary_planning(d) {
    const it = d.itinerary || {};
    const days = it.daily_plans || [];
    if (d.error) return card('ALIGO / ITINERARY', '行程规划', '', '<p>' + esc(d.error) + '</p>');
    const body = days.map((day) => {
      const acts = (day.activities || day.time_slots || []).map((a) => {
        const t = a.time || a.time_slot || '';
        const name = a.activity || a.place || a.title || '';
        const detail = a.detail || a.description || a.transport || '';
        return '<div class="list"><div><span><b>' + esc(t) + '</b> ' + esc(name) + '</span>' +
          '<span class="muted">' + esc(detail).slice(0, 60) + '</span></div></div>';
      }).join('');
      return '<div style="margin:10px 0 4px;font-weight:600">第 ' + esc(day.day || '') + ' 天 ' +
        '<span class="muted" style="font-weight:400">' + esc(day.city || day.date || '') + '</span></div>' + acts;
    }).join('');
    return card('ALIGO / ITINERARY', it.title || '行程规划',
      (it.duration || '') + ' · ' + days.length + ' 天', body || '<p class="muted">无行程内容</p>');
  },

  train_ticket(d) {
    const rows = ((d.results || {}).trains) || d.trains || [];
    const list = rows.slice(0, 8).map((t) => {
      const seats = ['二等座', '一等座', '商务座'].map((k) => {
        const v = (t.seats || t[k] || '') + '';
        const has = v && v !== '无' && v !== '0';
        return '<span class="chip' + (has ? ' a' : '') + '">' + k + ' ' + (esc(v) || '—') + '</span>';
      }).join('');
      return '<tr><td><b>' + esc(t.train_code || t.code || '') + '</b></td>' +
        '<td>' + esc(t.depart_time || t.start || '') + ' → ' + esc(t.arrive_time || t.end || '') + '</td>' +
        '<td>' + esc(t.duration || '') + '</td><td>' + seats + '</td></tr>';
    }).join('');
    const body = '<table><thead><tr><th>车次</th><th>时间</th><th>历时</th><th>余票</th></tr></thead>' +
      '<tbody>' + list + '</tbody></table>' + (rows.length > 8 ? '<p class="muted">共 ' + rows.length + ' 趟，此处展示前 8 趟</p>' : '');
    return card('ALIGO / RAIL', d.answer ? '车次列表' : '余票查询', rows.length + ' 趟', body);
  },

  rag_knowledge(d) {
    const src = (d.sources || []).map((s) => typeof s === 'string' ? s : (s.title || s.doc || JSON.stringify(s))).slice(0, 3);
    const body = '<div style="white-space:pre-wrap">' + esc(d.answer || '') + '</div>' +
      (src.length ? '<p class="muted" style="margin-top:10px">依据：' + src.map(esc).join(' · ') + '</p>' : '');
    return card('ALIGO / KNOWLEDGE', '知识库（树索引检索）', '带出处', body);
  },

  information_query(d) {
    const w = d.weather || {};
    const temp = w.temp || w.temperature || '';
    const body = (temp ? '<div class="big">' + esc(temp) + '°C</div>' : '') +
      '<p>' + esc(d.answer || w.summary || '') + '</p>';
    return card('ALIGO / INFO', '天气信息', w.city || '', body);
  },

  expense_tracking(d) {
    if (d.action === 'record' && d.expense) {
      const e = d.expense;
      const body = '<div style="text-align:center"><div class="muted">' + esc(e.category || '') + ' · ' +
        esc(e.description || '') + '</div><div class="big">¥ ' + money(e.amount) + '</div></div>' +
        (d.total_after != null ? '<div class="list"><div><span>累计报销</span><span>¥ ' + money(d.total_after) + '</span></div></div>' : '');
      return card('ALIGO / EXPENSE', '费用已记录', '已记录', body);
    }
    const body = '<p>' + esc(d.answer || '无费用记录') + '</p>';
    return card('ALIGO / EXPENSE', '费用汇总', '', body);
  },

  currency_conversion(d) {
    const body = '<div class="row between"><span class="chip">' + esc(d.from || '') + '</span>' +
      '<span class="muted">' + esc(d.amount) + ' ' + esc(d.from || '') + '</span></div>' +
      '<div style="text-align:center;color:var(--accent);margin:6px 0">↓</div>' +
      '<div class="row between" style="background:var(--tint);border:1px solid rgba(184,60,34,.3);padding:8px">' +
      '<span class="chip a">' + esc(d.to || '') + '</span>' +
      '<span class="big" style="font-size:18px">' + money(d.result) + ' ' + esc(d.to || '') + '</span></div>' +
      (d.rate ? '<p class="muted" style="margin-top:10px">1 ' + esc(d.from) + ' = ' + esc(d.rate) + ' ' + esc(d.to) + '</p>' : '');
    return card('ALIGO / FX', '汇率换算', '', body);
  },

  preference(d) {
    const list = ((d.preferences) || []).map((p) => {
      const v = Array.isArray(p.value) ? p.value.join('、') : p.value;
      return '<div><span>' + esc(p.type || '') + '</span><span>' + esc(v) + '</span></div>';
    }).join('');
    return card('ALIGO / PREFERENCES', '偏好已保存', '', '<div class="list">' + list + '</div>');
  },
};

function card(eyebrow, title, badge, body) {
  return '<div class="card"><div class="hd"><div><div class="eyebrow">' + eyebrow + '</div>' +
    '<div class="title">' + esc(title) + '</div></div>' +
    (badge ? '<span class="badge">' + esc(badge) + '</span>' : '') + '</div>' +
    '<div class="bd">' + body + '</div></div>';
}

let currentKey = null;

function renderNav() {
  const nav = document.getElementById('scenes');
  nav.innerHTML = SCENES.map((s) =>
    '<button class="scene" data-key="' + s.key + '" aria-current="false">' +
    '<span class="k">' + s.key.toUpperCase() + '</span>' + s.label +
    '<span class="muted" style="display:block;font-size:10px">' + s.desc + '</span></button>'
  ).join('');
  nav.addEventListener('click', (e) => {
    const b = e.target.closest('.scene');
    if (b) load(b.dataset.key);
  });
}

async function load(key) {
  if (currentKey === key) return;
  currentKey = key;
  document.querySelectorAll('.scene').forEach((b) => b.setAttribute('aria-current', String(b.dataset.key === key)));
  const q = document.getElementById('q');
  const ans = document.getElementById('ans');
  const cardBox = document.getElementById('card');
  const mt = document.getElementById('mt');
  const ms = document.getElementById('ms');
  q.textContent = '加载中…'; ans.textContent = ''; cardBox.innerHTML = '';
  try {
    const res = await fetch(DATA + key + '.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const d = await res.json();
    q.textContent = d.query || '';
    const c = d.complete || {};
    const results = c.results || [];
    const first = results[0] || {};
    const data = first.data || {};
    const intent = ((d.intent || {}).intents || [])[0] || {};
    mt.textContent = 'ALIGO / 行囊文件';
    ms.textContent = intent.type ? intent.type + ' · ' + Math.round((intent.confidence || 0) * 100) + '%' : '';
    ans.textContent = data.answer || '';
    const fn = RENDER[first.agent_name];
    cardBox.innerHTML = fn ? fn(data) : card('ALIGO / ' + String(first.agent_name || '').toUpperCase(), '结果', '', '<pre style="white-space:pre-wrap;font-size:11px">' + esc(JSON.stringify(data, null, 1)).slice(0, 1500) + '</pre>');
  } catch (err) {
    q.textContent = '加载失败';
    ans.textContent = String(err.message || err);
  }
}

renderNav();
load(SCENES[0].key);