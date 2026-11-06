import inspect, re
from agentscope.model._openai_chat._model import OpenAIChatModel
src = inspect.getsource(OpenAIChatModel._call_api)
for m in re.finditer(r".*generate_kwargs.*", src):
    print(m.group(0).strip())
print("---- lines mentioning update/|=")
for l in src.splitlines():
    if "kwargs.update" in l or "kwargs |= " in l or "**generate_kwargs" in l:
        print(l.strip())
