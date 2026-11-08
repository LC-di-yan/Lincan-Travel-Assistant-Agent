"""录制真实交互，供静态 demo 页回放。"""
import json, os, time, urllib.request

BASE = 'http://127.0.0.1:3003'
OUT = 'docs/demo/data'
os.makedirs(OUT, exist_ok=True)

SCENES = [
    ('itinerary', '明天北京到上海，3 天，预算 2000'),
    ('train', '北京到上海的高铁票'),
    ('rag', '出差住宿标准是多少'),
    ('weather', '北京天气怎么样'),
    ('expense', '记一笔打车费 50 元'),
    ('currency', '100 美元等于多少人民币'),
    ('preference', '我喜欢住万豪，座位要靠窗，请记住'),
]

def record(msg, user):
    payload = json.dumps({'message': msg, 'user_id': user}).encode()
    req = urllib.request.Request(BASE + '/api/chat', data=payload,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    events, last, intent, complete, deltas = [], None, None, None, []
    with urllib.request.urlopen(req, timeout=240) as r:
        for raw in r:
            s = raw.decode('utf-8', 'replace').strip()
            if s.startswith('event:'):
                last = s[6:].strip()
            elif s.startswith('data:'):
                try:
                    d = json.loads(s[5:].strip())
                except Exception:
                    continue
                if last == 'intention': intent = d
                elif last == 'complete': complete = d
                elif last == 'delta': deltas.append(d)
                events.append({'event': last, 'data': d})
    return {'intent': intent, 'complete': complete, 'deltas': deltas, 'events_count': len(events)}

index = []
for key, q in SCENES:
    t0 = time.time()
    try:
        data = record(q, 'demo_replay')
        data['query'] = q
        data['key'] = key
        path = os.path.join(OUT, key + '.json')
        json.dump(data, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
        agents = [x.get('agent_name') for x in (data.get('complete') or {}).get('results', [])]
        print('OK  %-11s %4.0fs agents=%s size=%dKB' % (key, time.time()-t0, agents, os.path.getsize(path)//1024))
        index.append({'key': key, 'query': q})
    except Exception as e:
        print('ERR %-11s %s: %s' % (key, type(e).__name__, str(e)[:90]))

json.dump(index, open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('recorded', len(index), 'scenes')