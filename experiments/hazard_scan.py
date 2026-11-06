import re
from pathlib import Path
ROOT = Path(".")
SKIP = re.compile(r"venv|node_modules|site-packages|__pycache__|experiments")
pats = {
    "slice/len on content": r"\.content\[|len\([^)]*\.content\)",
    "content.strip/startswith": r"\.content\.(strip|startswith|endswith|split|replace|format)\(",
    "json.loads(content)": r"json\.loads\([^)]*content",
    "str(content)": r"str\([^)]*content",
    "fstring content": r"\{[^}]*\.content[:}]",
    "model call": r"await (self\.)?model\(|model\.\w+\(|await .*_model\(",
    "formatter": r"[Ff]ormatter",
}
hits = {}
for k, p in pats.items():
    out = []
    for f in ROOT.rglob("*.py"):
        if SKIP.search(str(f)):
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, l in enumerate(txt.splitlines(), 1):
            if re.search(p, l) and not l.strip().startswith("#"):
                out.append(str(f) + ":" + str(i) + ": " + " ".join(l.split())[:120])
    hits[k] = out
    print("### " + k + " (" + str(len(out)) + " hits)")
    for h in out[:14]:
        print("   " + h)
    print()