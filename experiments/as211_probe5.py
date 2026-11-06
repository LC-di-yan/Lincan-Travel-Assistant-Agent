import ast, re, zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
def read(p):
    return z.read("agentscope/" + p).decode("utf-8", "replace")
def subfiles(top):
    return [n.split("agentscope/", 1)[1] for n in z.namelist() if n.startswith("agentscope/" + top + "/") and n.endswith(".py")]
def probe(modpath, clsnames):
    try:
        tree = ast.parse(read(modpath))
    except Exception as e:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in clsnames:
            print("--- " + node.name + " (" + modpath + ") ---")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                    a = item.args
                    print("   __init__(%s)" % ", ".join(x.arg for x in list(a.posonlyargs) + list(a.args))[:340])
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in ("__call__", "load", "discover", "reply"):
                    a = item.args
                    print("   " + item.name + "(%s)" % ", ".join(x.arg for x in list(a.posonlyargs) + list(a.args))[:240])
print("### skill files: " + ", ".join(subfiles("skill")))
for s in subfiles("skill"):
    probe(s, {"Skill", "LocalSkillLoader", "SkillLoaderBase"})
all_skill = "".join(read(f) for f in subfiles("skill"))
print("  SKILL.md literal count: " + str(all_skill.count("SKILL.md")))
for m in re.finditer(r"(def (load|discover)\([^)]*\)[^:]*):", all_skill):
    print("  " + " ".join(m.group(1).split())[:200])
print("### tool")
for s in subfiles("tool"):
    if s.count("/") <= 2:
        probe(s, {"FunctionTool", "Toolkit", "ToolBase", "AskUser", "ToolMiddlewareBase", "LocalBackend"})
print("### app files: " + ", ".join(subfiles("app")))
t = "".join(read(f) for f in subfiles("app"))
for m in re.finditer(r"def create_app\(([^)]*)\)", t):
    print("  create_app(" + " ".join(m.group(1).split())[:600] + ")")
print("### permission enums")
pt = "".join(read(f) for f in subfiles("permission"))
print("  modes: " + ", ".join(re.findall(r"^\s+([A-Z_]{3,}) = ", pt, re.M))[:400])
print("### state AgentState fields")
st = subfiles("state")
for s in st:
    try:
        tree = ast.parse(read(s))
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentState":
            fl = [i.target.id for i in node.body if isinstance(i, ast.AnnAssign) and isinstance(i.target, ast.Name)]
            print("  AgentState: " + ", ".join(fl[:20]))
print("### pipeline")
for s in subfiles("pipeline"):
    probe(s, {"GoalPipeline", "TeamPipeline", "TeamMember"})