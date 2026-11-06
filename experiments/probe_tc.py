import inspect
from agentscope.tool import ToolChoice
print("ToolChoice:", inspect.signature(ToolChoice.__init__))
print("fields:", list(ToolChoice.model_fields) if hasattr(ToolChoice, "model_fields") else "?")
print((inspect.getdoc(ToolChoice) or "")[:400])
