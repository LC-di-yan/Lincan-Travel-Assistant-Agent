import inspect
from agentscope.tool import Toolkit, FunctionTool, ToolBase

print("Toolkit.__init__:", inspect.signature(Toolkit.__init__))
for m in ["register", "get_tool", "call_tool", "list_tools", "get_json_schemas", "clear"]:
    if hasattr(Toolkit, m):
        print(f"Toolkit.{m}:", inspect.signature(getattr(Toolkit, m)))
print()
print("FunctionTool.__init__:", inspect.signature(FunctionTool.__init__))
print("ToolBase attrs:", [a for a in dir(ToolBase) if not a.startswith("_")][:14])
print()
doc = inspect.getdoc(FunctionTool) or ""
print("FunctionTool doc (head):", doc[:600])
