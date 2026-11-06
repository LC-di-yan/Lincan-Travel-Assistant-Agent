import re, zipfile, ast
from pathlib import Path
ROOT = Path(".")
SKIP = re.compile(r"venv|node_modules|site-packages|__pycache__|experiments")
n = 0; files = []
for f in ROOT.rglob("*.py"):
    if SKIP.search(str(f)): continue
    t = f.read_text(encoding="utf-8", errors="replace")
    c = len(re.findall(r"OpenAIChatModel\(", t))
    if c: n += c; files.append(str(f) + ":" + str(c))
print("OpenAIChatModel 构造点总数 =", n, "|", ", ".join(files))
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
log = z.read("agentscope/_logging.py" if "agentscope/_logging.py" in z.namelist() else "agentscope/_logging/__init__.py").decode("utf-8","replace")
print("--- setup_logger ---")
for l in log.splitlines():
    if "def setup_logger" in l or "def logger" in l:
        print("  " + l.strip()[:200])
mdl = z.read("agentscope/model/_openai_chat/_model.py").decode("utf-8","replace")
print("--- Parameters 定义/引用 ---")
print("  class Parameters:", bool(re.search(r"^class Parameters", mdl, re.M)))
for l in mdl.splitlines():
    if "Parameters" in l and ("class " in l or "parameters" in l.lower()) and not l.strip().startswith("#"):
        print("  > " + l.strip()[:170])
init = z.read("agentscope/model/_openai_chat/__init__.py").decode("utf-8","replace")
print("  _openai_chat/__init__.py:", " ".join(init.split())[:300])
base = z.read("agentscope/model/_base.py").decode("utf-8","replace")
for l in base.splitlines():
    if "Parameters" in l:
        print("  base> " + l.strip()[:170])