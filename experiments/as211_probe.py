import ast, zipfile, re
from pathlib import Path

WHEEL = next(Path("C:/Users/86134/AppData/Local/Temp/as211").glob("*.whl"))
z = zipfile.ZipFile(WHEEL)
names = z.namelist()

def read(p):
    return z.read("agentscope/" + p).decode("utf-8", "replace")

print("=== model/ files ===")
print(", ".join(n.split("agentscope/",1)[1] for n in names if n.startswith("agentscope/model/") and n.endswith(".py")))

print("=== openai model class ===")
for f in [n for n in names if n.startswith("agentscope/model/") and "openai" in n and n.endswith(".py")]:
    short = f.split("agentscope/",1)[1]
    tree = ast.parse(read(short))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and "Model" in node.name:
            print("  file=%s class=%s" % (short, node.name))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                    a = item.args
                    print("    __init__(%s)" % ", ".join(x.arg for x in list(a.posonlyargs)+list(a.args))[:400])

print("=== ChatResponse fields ===")
tree = ast.parse(read("model/_model_response.py"))
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        fl = [i.target.id for i in node.body if isinstance(i, ast.AnnAssign) and isinstance(i.target, ast.Name)]
        print("  %s: %s" % (node.name, ", ".join(fl[:14])))

print("=== tool/__init__ exports ===")
t = read("tool/__init__.py")
m = re.search(r"__all__ = (\[.*?\])", t, re.S)
print("  " + (m.group(1).replace("\n"," ").replace('"',"")[:600] if m else t[:300]))

print("=== EventType members ===")
t = read("event/_event.py")
print("  " + ", ".join(re.findall(r"^    ([A-Z_]+) = ", t, re.M))[:1200])

print("=== def init anywhere? ===")
hits = []
for n in names:
    if n.endswith(".py"):
        c = z.read(n).decode("utf-8", "replace")
        if re.search(r"^def init\(", c, re.M):
            hits.append(n)
print("  " + (", ".join(hits) if hits else "NONE -> agentscope.init removed"))

print("=== Msg content rules ===")
mb = read("message/_base.py")
i = mb.find("def validate_role_content")
print(mb[max(0,i-300):i+1600])