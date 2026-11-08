/* Aligo 演示用 mock 后端。
 * 在真实前端构建产物上拦截 /api/*，用项目真实运行录制的数据回放，
 * 使静态托管（GitHub Pages）上也能完整「对话」。
 * 不联网、不含任何密钥。
 */
(function () {
  const realFetch = window.fetch.bind(window);
  const SCENES = {};
  const ORDER = ['itinerary', 'train', 'rag', 'weather', 'expense', 'currency', 'preference'];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* 关键词 → 场景。命中不了的走兜底。 */
  const RULES = [
    { key: 'itinerary', re: /(行程|规划|安排|几天|\d\s*天|天\d*晚|怎么走)/ },
    { key: 'train', re: /(高铁|火车|车票|动车|余票|车次|G\d{2,4})/ },
    { key: 'rag', re: /(标准|规定|政策|报销|制度|上限|额度|签证|流程|材料)/ },
    { key: 'weather', re: /(天气|气温|下雨|温度|穿什么)/ },
    { key: 'expense', re: /(记一笔|记账|花了|报销单|费用记录|\d+\s*元)/ },
    { key: 'currency', re: /(美元|欧元|日元|港币|汇率|换算|兑换|人民币)/ },
    { key: 'preference', re: /(喜欢|偏好|记住|以后都|习惯|常驻|靠窗)/ },
  ];

  async function loadScenes() {
    await Promise.all(ORDER.map(async (k) => {
      try {
        const res = await realFetch('data/' + k + '.json', { cache: 'no-store' });
        if (res.ok) SCENES[k] = await res.json();
      } catch (e) { /* 忽略单个场景失败 */ }
    }));
  }

  const norm = (s) => String(s || '').replace(/\s+/g, '').toLowerCase();

  function pick(query) {
    const q = norm(query);
    for (const r of RULES) if (r.re.test(q) && SCENES[r.key]) return r.key;
    return null;
  }

  const sse = (event, data) => 'event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n';

  function streamResponse(frames) {
    const enc = new TextEncoder();
    const body = new ReadableStream({
      async start(controller) {
        for (const [chunk, delay] of frames) {
          if (delay) await sleep(delay);
          controller.enqueue(enc.encode(chunk));
        }
        controller.close();
      },
    });
    return new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store' },
    });
  }

  function replayChat(query) {
    const key = pick(query);
    const scene = key ? SCENES[key] : null;
    const frames = [];
    frames.push([sse('thinking', { status: 'analyzing_intent' }), 260]);

    if (!scene) {
      const notice = {
        status: 'completed',
        intention: { intents: [{ type: 'demo_hint', confidence: 0.99, description: '演示未覆盖' }], key_entities: {} },
        agents_executed: 0,
        results: [],
        demo_notice: '这是静态演示，覆盖：行程规划 / 火车票 / 知识库问答 / 天气 / 费用记录 / 汇率 / 偏好记忆。试试点击上方的示例问法。',
      };
      frames.push([sse('intention', notice.intention), 380]);
      frames.push([sse('dispatching', { agents: [] }), 200]);
      frames.push([sse('thinking', { status: 'executing_agents' }), 200]);
      frames.push([sse('complete', notice), 120]);
      return streamResponse(frames);
    }

    const intent = scene.intent || { intents: [], key_entities: {} };
    frames.push([sse('intention', intent), 420]);

    const complete = scene.complete || { status: 'completed', results: [] };
    const results = complete.results || [];
    frames.push([sse('dispatching', { agents: results.map((r, i) => ({ agent_name: r.agent_name, priority: i + 1 })) }), 320]);
    frames.push([sse('thinking', { status: 'executing_agents' }), 260]);

    results.forEach((r, i) => {
      frames.push([sse('agent_start', { agent_name: r.agent_name }), i === 0 ? 420 : 160]);
      frames.push([sse('agent_result', r), 520]);
    });

    frames.push([sse('complete', complete), 220]);
    return streamResponse(frames);
  }

  /* 侧栏数据：从录制结果里挑能展示的部分，保持「像真的」 */
  function buildSidebar() {
    const res = {};
    const exp = (SCENES.expense || {}).complete;
    if (exp) {
      const results = exp.results || [];
      const d = (results[0] || {}).data || {};
      const item = d.expense || { category: '交通', amount: 50, description: '打车费', date: '2026-11-08' };
      res.expenses = {
        total: item.amount || 50,
        count: 1,
        by_category: { [item.category || '交通']: item.amount || 50 },
        items: [item],
      };
    }
    const pref = (SCENES.preference || {}).complete;
    if (pref) {
      const d = ((pref.results || [])[0] || {}).data || {};
      res.preferences = d.preferences || [];
    }
    return res;
  }

  /* 侧栏数据依赖已加载的场景，改为加载完成后填充，并在接口返回前等待就绪 */
  let sidebar = {};
  const ready = loadScenes().then(() => { sidebar = buildSidebar(); });

  const json = (data) => new Response(JSON.stringify(data), {
    status: 200, headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });

  const PLUGINS = {
    plugins: [
      { name: 'plan-trip', enabled: true, description: '行程规划' },
      { name: 'place-search', enabled: true, description: '地点搜索（高德 POI）' },
      { name: 'ask-question', enabled: true, description: '知识库问答（树索引）' },
      { name: 'train-ticket', enabled: true, description: '火车票查询' },
      { name: 'query-info', enabled: true, description: '天气与信息查询' },
      { name: 'expense-tracker', enabled: true, description: '费用记录' },
      { name: 'currency-converter', enabled: true, description: '汇率换算' },
      { name: 'preference', enabled: true, description: '偏好管理' },
      { name: 'visa-info', enabled: true, description: '签证政策' },
      { name: 'translation', enabled: true, description: '多语言翻译' },
    ],
  };

  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (!url.startsWith('/api/')) return realFetch(input, init);

    await ready;                       // 确保场景数据已加载
    const path = url.split('?')[0];

    if (path === '/api/chat') {
      let query = '';
      try { query = JSON.parse((init && init.body) || '{}').message || ''; } catch (e) {}
      return replayChat(query);
    }
    if (path === '/api/session/new') return json({ session_id: 'demo-' + Date.now() });
    if (path === '/api/preferences') return json({ preferences: sidebar.preferences || [] });
    if (path === '/api/expenses') return json(sidebar.expenses || { total: 0, count: 0, by_category: {}, items: [] });
    if (path === '/api/history') return json({ trips: [], frequent_destinations: [] });
    if (path === '/api/context') return json({ messages: [] });
    if (path === '/api/plugins') return json(PLUGINS);
    if (path === '/api/tts/personas') return json({ personas: [{ id: 'loli_guide', label: '小冰 · 萝莉导游' }] });
    /* 其余（TTS / 朗读）在静态演示中不可用，返回空流由前端降级 */
    return new Response('', { status: 204 });
  };

})();