import ast, re, zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
def read(p):
    return z.read("agentscope/" + p).decode("utf-8", "replace")
def probe(modpath, clsnames):
    try:
        tree = ast.parse(read(modpath))
    except Exception as e:
        print("  " + modpath + " FAIL " + repr(e)[:90]); return
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in clsnames:
            print("--- " + node.name + " (" + modpath + ") ---")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                    a = item.args
                    print("   __init__(%s)" % ", ".join(x.arg for x in list(a.posonlyargs) + list(a.args))[:330])
            ms = [i.name for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and not i.name.startswith("_")]
            if ms: print("   methods: " + ", ".join(ms[:10]))
print("### middleware")
for p in [n for n in z.namelist() if n.startswith("agentscope/middleware/") and n.endswith(".py")]:
    print("  file: " + p.split("middleware/")[1])
probe("middleware/__init__.py", set())
import itertools
sub = [n.split("agentscope/",1)[1] for n in z.namelist() if n.startswith("agentscope/middleware/") and n.endswith(".py")]
for s in sub:
    probe(s, {"ModelRouterMiddleware", "ReplyBudgetControlMiddleware", "RAGMiddleware", "Mem0Middleware", "ReMeMiddleware", "AgenticMemoryMiddleware", "MiddlewareBase", "TTSMiddleware"})
print("### skill")
for s in [n.split("agentscope/",1)[1] for n in z.namelist() if n.startswith("agentscope/skill/") and s_ok if False]:
    pass
sfiles = [n.split("agentscope/",1)[1] for n in z.namelist() if n.startswith("agentscope/skill/") and n.endswith(".py")]
print("  files: " + ", ".join(sfiles))
for s in sfiles:
    probe(s, {"Skill", "LocalSkillLoader", "SkillLoaderBase"})
txt = read("skill/_local_loader.py") if "skill/_local_loader.py" in [f for f in sfiles] else ""
print("  SKILL.md mentions: " + str(len(re.findall("SKILL.md", "".join(read(f) for f in sfiles)))))
print("### tool FunctionTool / Toolkit")
tfiles = [n.split("agentscope/",1)[1] for n in z.namelist() if n.startswith("agentscope/tool/") and n.endswith(".py") and n.count("/") <= 3]
for s in tfiles:
    probe(s, {"FunctionTool", "Toolkit", "ToolBase", "AskUser", "ParamsBase"})
print("### app.create_app")
afiles = [n.split("agentscope/",1)[1] for n in z.namelist() if n.startswith("agentscope/app/") and n.endswith(".py") and n.count("/") <= 2]
print("  files: " + ", ".join(afiles))
for s in afiles:
    try:
        t = read(s)
        m = re.search(r"def create_app\(([^)]*)\)", t)
        if m:
            print("  create_app(" + " ".join(m.group(1).split())[:500] + ")")
    except Exception:
        pass
print("### PermissionMode members")
pfiles = [n.split("agentscope/",1)[1] for n in z.namelist() if n.startswith("agentscope/permission/") and n.endswith(".py")]
t = "".join(read(f) for f in pfiles)
print("  " + ", ".join(re.findall(r"^\s+([A-Z_]+) = ", t, re.M))[:400])