import json, socket, urllib.request, urllib.error

host = "tokenrhythm.studio"
try:
    print("DNS:", socket.gethostbyname(host))
except Exception as e:
    print("DNS FAIL:", e)

body = json.dumps({"model": "NeoHorse-Jev-4B", "state": "test",
                   "questions": {"q1": {"type": "noul", "instructions": "test"}}}).encode()
for path in ["/v1/systemone", "/v1/decision", "/v1/models"]:
    req = urllib.request.Request("https://" + host + path, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(path, "->", r.status, r.read()[:100])
    except urllib.error.HTTPError as e:
        print(path, "-> HTTP", e.code, e.read()[:120])
    except Exception as e:
        print(path, "->", type(e).__name__, str(e)[:120])
