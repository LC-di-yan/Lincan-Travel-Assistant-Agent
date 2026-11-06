import ast, re, zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
def read(p):
    return z.read("agentscope/" + p).decode("utf-8", "replace")
def subs(top):
    return [n.split("agentscope/", 1)[1] for n in z.namelist() if n.startswith("agentscope/" + top + "/") and n.endswith(".py")]
print("=== top-level __all__ ===")
print(read("__init__.py"))
print("=== pipeline ===")
for f in subs("pipeline"):
    t = read(f)
    for node in ast.parse(t).body:
        if isinstance(node, ast.ClassDef):
            inits = [i for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and i.name == "__init__"]
            sig = ""
            if inits:
                a = inits[0].args
                sig = "(" + ", ".join(x.arg for x in list(a.posonlyargs) + list(a.args)) + ")"
            print("  " + f + " :: class " + node.name + " " + sig[:200])
print("=== permission enums/fields ===")
pt = "".join(read(f) for f in subs("permission"))
for m in re.finditer(r"class (\w+)\(([^)]*)\):", pt):
    print("  " + m.group(1) + "(" + m.group(2) + ")")
print("  ALLOW/etc values: " + ", ".join(sorted(set(re.findall(r"^\s+([A-Z_]{3,}) = ", pt, re.M))))[:300])
print("=== classifier models ===")
for f in subs("classifier"):
    t = read(f)
    for node in ast.parse(t).body:
        if isinstance(node, ast.ClassDef) and "Classifier" in node.name:
            inits = [i for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and i.name == "__init__"]
            sig = ""
            if inits:
                a = inits[0].args
                sig = "(" + ", ".join(x.arg for x in list(a.posonlyargs) + list(a.args)) + ")"
            print("  " + node.name + " " + sig[:220] + "   [" + f + "]")
print("=== state.AgentState fields ===")
for f in subs("state"):
    for node in ast.parse(read(f)).body:
        if isinstance(node, ast.ClassDef) and node.name in ("AgentState", "Task", "ReplyContext"):
            fl = [i.target.id for i in node.body if isinstance(i, ast.AnnAssign) and isinstance(i.target, ast.Name)]
            print("  " + node.name + ": " + ", ".join(fl[:16]))
print("=== AskUser / ToolBase ===")
for f in subs("tool"):
    for node in ast.parse(read(f)).body:
        if isinstance(node, ast.ClassDef) and node.name in ("AskUser", "ToolBase", "ToolMiddlewareBase"):
            inits = [i for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and i.name == "__init__"]
            sig = "(" + ", ".join(x.arg for x in list(inits[0].args.posonlyargs) + list(inits[0].args.args)) + ")" if inits else ""
            meth = [i.name for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and not i.name.startswith("_")]
            print("  " + node.name + sig[:160] + " | " + ", ".join(meth[:12]))