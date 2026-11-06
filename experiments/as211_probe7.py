import re, zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
src = z.read("agentscope/model/_openai_chat/_model.py").decode("utf-8", "replace")
base = z.read("agentscope/model/_base.py").decode("utf-8", "replace")
print("=== OpenAIChatModel._call_api signature ===")
m = re.search(r"def _call_api\(([^)]*)\)", src)
print("  " + " ".join(m.group(0).split())[:400] if m else "none")
print("=== per-call kwargs plumbing in _base.__call__ ===")
i = base.find("async def __call__")
print(base[i:i + 2000])