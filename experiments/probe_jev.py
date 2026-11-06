import inspect
from agentscope.classifier import JevClassifierModel, ClassifierModelBase
print("JevClassifierModel.__init__:", inspect.signature(JevClassifierModel.__init__))
print("ClassifierModelBase.__init__:", inspect.signature(ClassifierModelBase.__init__))
print()
try:
    from agentscope.credential import CredentialFactory
    print("CredentialFactory:", [m for m in dir(CredentialFactory) if not m.startswith("_")])
except Exception as e:
    print("no CredentialFactory:", e)
print()
import agentscope.classifier as C
print("classifier exports:", [n for n in dir(C) if not n.startswith("_")])
