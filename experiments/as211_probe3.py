import re, zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
mb = z.read("agentscope/message/_base.py").decode("utf-8", "replace")
print("=== how UserMsg/AssistantMsg/SystemMsg are defined ===")
for l in mb.splitlines():
    if re.match(r"^(class|def) (Msg|UserMsg|AssistantMsg|SystemMsg|Usage|_to_blocks)", l):
        print("  " + l.strip()[:200])
print("=== __all__ of message ===")
mi = z.read("agentscope/message/__init__.py").decode("utf-8", "replace")
print(mi[:1200])
print("=== _to_blocks body ===")
i = mb.find("def _to_blocks")
print(mb[i:i + 500])
print("=== formatter __all__ ===")
fm = z.read("agentscope/formatter/__init__.py").decode("utf-8", "replace")
m = re.search(r"__all__ = (\[(.*?)\])", fm, re.S)
print(", ".join(x.strip().strip(chr(34) + ",") for x in (m.group(2).split(chr(10)) if m else []) if x.strip()))
print("=== Msg class docstring/fields head ===")
j = mb.find("class Msg")
print(mb[j:j + 1500])