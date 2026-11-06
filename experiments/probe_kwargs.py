import inspect
from agentscope.model._openai_chat._model import OpenAIChatModel
src = inspect.getsource(OpenAIChatModel._call_api)
i = src.find("kwargs: dict[str, Any]")
print(src[i:i + 1400])
