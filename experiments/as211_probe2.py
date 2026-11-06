import ast, re, zipfile
from pathlib import Path
WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
def read(p):
    return z.read("agentscope/" + p).decode("utf-8", "replace")
def exports(mod):
    try:
        t = read(mod + "/__init__.py")
    except KeyError:
        return "MISSING"
    m = re.search(r"__all__ = (\[(.*?)\])", t, re.S)
    if m:
        return ", ".join(x.strip().strip(chr(34)) for x in m.group(2).split(chr(10)) if x.strip().strip(chr(34) + ","))
    return ", ".join(sorted(set(re.findall(r"\b(\w+)\b", str(re.findall(r"import (\w+)", t))))))[:400]
for mod in ["middleware", "classifier", "rag", "pipeline", "tool", "workspace", "permission", "app", "state", "embedding", "realtime", "skill", "sop"]:
    print("### " + mod + ": " + exports(mod)[:520])
print()
print("=== OpenAIChatModel Parameters + __call__ ===")
src = read("model/_openai_chat/_model.py")
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        fl = [i.target.id for i in node.body if isinstance(i, ast.AnnAssign) and isinstance(i.target, ast.Name)]
        meth = [i.name for i in node.body if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef))]
        print("  class " + node.name + " fields=" + ",".join(fl[:12]) + " methods=" + ",".join([m for m in meth if not m.startswith("__")][:12]))
m = re.search(r"def __call__\(([^)]*)\)([^:]*)", src)
print("  __call__(%s) -> %s" % (m.group(1).replace(chr(10), " ")[:200], m.group(2).strip()[:120]) if m else "  no __call__")
print()
print("=== ChatModelBase __call__ ===")
b = read("model/_base.py")
for m in re.finditer(r"(async def|def) (__call__|__call_with_retry__)\(([^{]*)\)", b):
    print("  " + " ".join(m.group(0).split())[:300])
print()
print("=== UserMsg/AssistantMsg source ===")
mb = read("message/_base.py")
i = mb.find("class UserMsg")
print(mb[i:i + 900] if i > 0 else "UserMsg not found")