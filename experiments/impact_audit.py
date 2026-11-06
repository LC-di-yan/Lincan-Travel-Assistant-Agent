import re, zipfile, ast
from pathlib import Path
from collections import defaultdict

# --- 1) does 2.x Msg accept a plain string content? ---
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
mb = z.read("agentscope/message/_base.py").decode("utf-8", "replace")
for l in mb.splitlines():
    if re.match(r"\s+(content|role|name|metadata)\s*:", l) or "field_validator" in l or "model_validator" in l:
        print("MSG> " + l.strip()[:150])
i = mb.find("_assert_user_content_blocks")
print("--- _assert_user_content_blocks ---")
print(mb[i:i+700])

# --- 2) project impact audit ---
ROOT = Path(".")
SKIP = re.compile(r"venv|node_modules|site-packages|__pycache__|^\\.git|\\.\\.env")
files = [p for p in ROOT.rglob("*.py") if not SKIP.search(str(p))]
rows = []
totals = defaultdict(int)
for p in files:
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    if "agentscope" not in txt and "Msg(" not in txt and ".content" not in txt:
        continue
    n_import = len(re.findall(r"from agentscope|import agentscope", txt))
    n_agentbase = len(re.findall(r"AgentBase", txt))
    n_msg = len(re.findall(r"\bMsg\(", txt))
    n_content = len(re.findall(r"\.content\b", txt))
    n_model_call = len(re.findall(r"\bmodel\s*\(|await model", txt))
    n_init = len(re.findall(r"agentscope\.init|config_agentscope", txt))
    n_fmt = len(re.findall(r"formatter", txt))
    if n_import or n_agentbase or n_msg or n_model_call or n_init:
        rows.append((str(p), n_import, n_agentbase, n_msg, n_content, n_model_call, n_init, n_fmt))
        for k, v in zip(("import","agentbase","msg","content","modelcall","init","formatter"), (n_import,n_agentbase,n_msg,n_content,n_model_call,n_init,n_fmt)):
            totals[k] += v
rows.sort(key=lambda r: (-r[3] - r[4] - r[2], r[0]))
print("--- top impact files (path, import, AgentBase, Msg(, .content, model-call, init, formatter) ---")
for r in rows[:35]:
    print("  " + " | ".join(str(x) for x in r))
print("TOTAL FILES AFFECTED:", len(rows))
print("TOTALS:", dict(totals))

# --- 3) config_agentscope.py full ---
for cand in list(ROOT.rglob("config_agentscope.py"))[:1]:
    print("--- " + str(cand) + " ---")
    print(cand.read_text(encoding="utf-8", errors="replace")[:2500])