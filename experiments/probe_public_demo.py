import json, time, urllib.request
BASE = 'https://844b3e816654c3.lhr.life'
def sse(payload):
    req = urllib.request.Request(BASE + '/api/chat', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    ev, last, complete = [], None, None
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            s = raw.decode('utf-8', 'replace').strip()
            if s.startswith('event:'):
                last = s[6:].strip(); ev.append(last)
            elif s.startswith('data:') and last == 'complete':
                try: complete = json.loads(s[5:].strip())
                except Exception: pass
    return ev, complete

t0 = time.time()
ev, comp = sse({'message': '记一笔打车费 88 元', 'user_id': 'public_demo'})
print('elapsed: %.0fs' % (time.time() - t0))
print('events:', ev)
if comp:
    print('status:', comp.get('status'))
    print('agents:', [r.get('agent_name') for r in (comp.get('results') or [])])
    d = (comp.get('results') or [{}])[0].get('data', {})
    print('data head:', json.dumps(d, ensure_ascii=False)[:180])