import inspect
from agentscope.tool import ToolResponse, ToolChunk
from agentscope.message import ToolCallBlock, TextBlock

print("ToolResponse:", inspect.signature(ToolResponse.__init__))
print("ToolResponse fields:", list(ToolResponse.model_fields) if hasattr(ToolResponse, "model_fields") else "?")
print()
print("ToolCallBlock fields:", list(ToolCallBlock.model_fields) if hasattr(ToolCallBlock, "model_fields") else "?")
print()
from agentscope.state import AgentState
print("AgentState:", inspect.signature(AgentState.__init__))
print("AgentState fields:", list(AgentState.model_fields))
