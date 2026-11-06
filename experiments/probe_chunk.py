import inspect
from agentscope.tool import ToolChunk
print("ToolChunk:", inspect.signature(ToolChunk.__init__))
print("fields:", list(ToolChunk.model_fields))
doc = inspect.getdoc(ToolChunk) or ""
print("doc:", doc[:400])
