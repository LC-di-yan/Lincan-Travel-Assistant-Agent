import inspect
from agentscope.classifier._jev import _model as jm
src = inspect.getsource(jm)
i = src.find("self.client = AsyncT")
print("--- client line ---")
print(src[i:i+520])
print()
import typesafe_sdk
from pathlib import Path
pkg = Path(typesafe_sdk.__file__).parent
for f in pkg.rglob("*.py"):
    t = f.read_text(encoding="utf-8", errors="replace")
    if "MIN_COMPRESSED_BODY_LENGTH" in t and "=" in t and "if" not in t.split("MIN_COMPRESSED_BODY_LENGTH")[0][-40:]:
        for line in t.splitlines():
            if line.strip().startswith("MIN_COMPRESSED_BODY_LENGTH"):
                print(f.name + ": " + line.strip())
# AsyncTypeSafeClient fields
from typesafe_sdk import AsyncTypeSafeClient
print("AsyncTypeSafeClient init:", inspect.signature(AsyncTypeSafeClient.__init__))
for a in ["compression", "config", "_config"]:
    print("has", a, ":", hasattr(AsyncTypeSafeClient, a))
