import typesafe_sdk, inspect, re
from pathlib import Path
pkg = Path(typesafe_sdk.__file__).parent
print("pkg dir:", pkg)
hits = []
for f in pkg.rglob("*.py"):
    txt = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r".*(?:url|path|endpoint|/v1|/decision|/classify|POST).*", txt):
        line = m.group(0).strip()
        if any(k in line.lower() for k in ("decision", "classify", "/v1", "endpoint", "url =", "path")):
            hits.append(f.name + ": " + line[:120])
seen = set()
for h in hits:
    if h not in seen:
        seen.add(h)
        print(h)
    if len(seen) > 25:
        break
