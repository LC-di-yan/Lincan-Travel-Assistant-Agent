import json, urllib.request, urllib.error

BASE = "https://token-api.matvenus.com/v1"
KEY = __import__("os").environ.get("PROBE_KEY", "")

def probe(method, path, body=None, auth=True):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": "Bearer " + KEY} if auth else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()[:220].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:220].decode("utf-8", "replace")
    except Exception as e:
        return "EXC", f"{type(e).__name__}: {str(e)[:120]}"

print("no-auth /v1/models:", probe("GET", "/models", auth=False))
print("with-key /v1/models:", probe("GET", "/models"))
print()
print("/v1/systemone :", probe("POST", "/systemone", {"model": "glm-5.3-flash", "state": "test",
                                                     "questions": {"q": {"type": "noul", "instructions": "t"}}}))
print("/v1/decision  :", probe("POST", "/decision", {"model": "glm-5.3-flash", "state": "test",
                                                    "questions": {"q": {"type": "noul", "instructions": "t"}}}))
