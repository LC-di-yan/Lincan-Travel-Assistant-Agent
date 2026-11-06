import inspect
from agentscope.classifier import JevClassifierModel, ClassifierModelBase
print("JevClassifierModel methods:", [m for m in dir(JevClassifierModel) if not m.startswith("_")])
print()
for name in ["classify", "ask", "decide", "run", "call"]:
    if hasattr(JevClassifierModel, name):
        print(name, inspect.signature(getattr(JevClassifierModel, name)))
print()
print("ClassifierResponse fields:", list(__import__('agentscope.classifier', fromlist=['ClassifierResponse']).ClassifierResponse.model_fields))
from agentscope.classifier import ClassifierResponse
resp = ClassifierResponse.model_fields
for k, v in resp.items():
    print(" ", k, ":", str(v.annotation)[:80])
