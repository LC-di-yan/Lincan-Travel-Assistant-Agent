import inspect
import agentscope.model as M
from agentscope.model import ChatModelBase, OpenAIChatModel

print("ChatModelBase.__call__:", inspect.signature(ChatModelBase.__call__))
src = inspect.getsource(OpenAIChatModel._call_api)
for kw in ["structured", "schema", "response_format", "json_schema"]:
    hits = [l.strip() for l in src.splitlines() if kw in l]
    print(f"-- {kw}: {len(hits)}")
    for h in hits[:4]:
        print("   ", h[:140])
