import inspect
from agentscope.model._openai_chat._model import OpenAIChatModel
src = inspect.getsource(OpenAIChatModel._call_api)
print(src[:1800])
