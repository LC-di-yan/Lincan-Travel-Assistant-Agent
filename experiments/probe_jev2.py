import inspect
from agentscope.classifier._jev import _model as jm
print(inspect.getsource(jm)[:2600])
