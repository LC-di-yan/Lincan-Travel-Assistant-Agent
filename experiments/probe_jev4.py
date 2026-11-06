import inspect
from agentscope.classifier import ClassifierModelBase, ClassifierResponse
from agentscope.classifier._base import ClassifierModelBase as CMB
print("ClassifierModelBase public:", [m for m in dir(ClassifierModelBase) if not m.startswith("_")])
print("__call__ sig:", inspect.signature(ClassifierModelBase.__call__))
print()
print("ClassifierResponse:", inspect.signature(ClassifierResponse.__init__))
src = inspect.getsource(ClassifierResponse)
print(src[:900])
