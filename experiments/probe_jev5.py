import inspect, asyncio
from agentscope.classifier._jev import _model as jm
from agentscope.classifier._question import BinaryQuestion, ChoiceQuestion

src = inspect.getsource(jm)
# __call__ 定义
for m in ["async def __call__", "def __call__"]:
    if m in src:
        i = src.find(m)
        print("Jev __call__ found:", m)
        print(src[i:i + 500])
        break
print()
print("BinaryQuestion fields:", list(BinaryQuestion.model_fields))
print("BinaryQuestion type literal:", BinaryQuestion.model_fields["type"].annotation)
print("ChoiceQuestion fields:", list(ChoiceQuestion.model_fields))
print()
# 判别联合是否接受裸 dict
q = {"q_intent": {"type": "choice", "instructions": "主要意图", "criteria": {"a": "x", "b": "y"}}}
print("dict passthrough test:")
from agentscope.classifier import ClassifierModelBase
try:
    ann = ClassifierModelBase.__call__
    print("  base __call__ is coroutine function:", asyncio.iscoroutinefunction(ann))
except Exception as e:
    print("  err:", e)
