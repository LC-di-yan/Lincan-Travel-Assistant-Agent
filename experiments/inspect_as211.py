import re
import zipfile
from pathlib import Path

WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
print("WHEEL:", WHEEL.name)

inits = [n for n in z.namelist() if n.startswith("agentscope/") and n.endswith("__init__.py")]
tops = sorted({n.split("/")[1] for n in inits if n.count("/") == 2})
print("=== subpackages ===")
print(", ".join(tops))


def dump(path, patterns, limit=60):
    print(f"=== {path} ===")
    try:
        txt = z.read("agentscope/" + path).decode("utf-8", "replace")
    except KeyError:
        print("  (missing)")
        return
    hits = []
    for l in txt.splitlines():
        s = l.strip()
        if any(re.match(p, s) for p in patterns):
            hits.append(s)
    for h in hits[:limit]:
        print("  " + h[:150])


dump("agent/__init__.py", [r"^(class |from |import )", r"^__all__"], 40)
dump("message/__init__.py", [r"^(class |from |import )", r"^__all__"], 40)
dump("model/__init__.py", [r"^(class |from |import )", r"^__all__"], 30)
dump("formatter/__init__.py", [r"^(class |from |import )", r"^__all__"], 20)
dump("__init__.py", [r"^(class |from |import |def |__all__)"], 30)
dump("credential/__init__.py", [r"^(class |from |import )"], 25)
dump("event/__init__.py", [r"^(class |from |import )", r"^__all__"], 30)

meta = next(n for n in z.namelist() if n.endswith("METADATA"))
mtxt = z.read(meta).decode("utf-8", "replace")
print("=== metadata ===")
for l in mtxt.splitlines():
    if l.startswith(("Requires-Python", "Provides-Extra", "Requires-Dist: mcp", "Requires-Dist: openai")):
        print("  " + l)

print("=== message module files ===")
for n in z.namelist():
    if n.startswith("agentscope/message/") and n.endswith(".py"):
        print("  " + n)
