import inspect
from agentscope.classifier._jev import _model as jm
src = inspect.getsource(jm)
i = src.find("TypeSafeClient")
print("--- JevClassifierModel client construction ---")
print(src[max(0,i-600):i+400])
print()
print("--- compression usage in sdk ---")
from pathlib import Path
pkg = Path(__import__("typesafe_sdk").__file__).parent
for f in pkg.rglob("*.py"):
    t = f.read_text(encoding="utf-8", errors="replace")
    if "compression" in t:
        for line in t.splitlines():
            if "compression" in line and ("zstd" in line or "is not None" in line or "default" in line or "Content-Length" in line.lower()):
                print(f.name + ": " + line.strip()[:130])
