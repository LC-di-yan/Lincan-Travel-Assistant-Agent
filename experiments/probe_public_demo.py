import json, time, urllib.request
BASE = 'https://7e1d02f18071d270-223-104-83-153.serveousercontent.com'

print('--- stability: 4 health probes ---')
ok = 0
for i in range(4):
    try:
        with urllib.request.urlopen(BASE + '/api/health', timeout=25) as r:
            ok += 1 if r.status == 200 else 0
    except Exception as e:
        print('  probe %d fail: %s' % (i + 1, str(e)[:60]))
    time.sleep(1)
print('  healthy: %d/4' % ok)

def sse(payload, timeout=180):
    req = urllib.request.Request(BASE + '/api/chat', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    ev, last, comp = [], None, None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            s = raw.decode('utf-8', 'replace').strip()
            if s.startswith('event:'):
                last = s[6:].strip(); ev.append(last)
            elif s.startswith('data:') and last == 'complete':
                try: comp = json.loads(s[5:].strip())
                except Exception: pass
    return comp

for q in ['100 美元等于多少人民币', '去泰国需要签证吗']:
    t0 = time.time()
    try:
        c = sse({'message': q, 'user_id': 'public_demo_v3'})
        agents = [x.get('agent_name') for x in (c or {}).get('results', [])]
        print('OK  %-22s %.0fs status=%s agents=%s' % (q, time.time() - t0, (c or {}).get('status'), agents))
    except Exception as e:
        print('ERR %-22s %s: %s' % (q, type(e).__name__, str(e)[:80]))