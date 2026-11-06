import inspect
from agentscope.classifier import ClassifierUsage
from agentscope.classifier._response import RefusalAnswer, BinaryAnswer, ChoiceAnswer
print("ClassifierUsage:", list(ClassifierUsage.model_fields) if hasattr(ClassifierUsage, "model_fields") else inspect.signature(ClassifierUsage.__init__))
print("RefusalAnswer:", list(RefusalAnswer.model_fields) if hasattr(RefusalAnswer, "model_fields") else inspect.signature(RefusalAnswer.__init__))
print("BinaryAnswer:", list(BinaryAnswer.model_fields) if hasattr(BinaryAnswer, "model_fields") else "?")
print("ChoiceAnswer:", list(ChoiceAnswer.model_fields) if hasattr(ChoiceAnswer, "model_fields") else "?")
from agentscope.classifier._response import ScoreAnswer
print("ScoreAnswer:", list(ScoreAnswer.model_fields) if hasattr(ScoreAnswer, "model_fields") else "?")
print()
# 各 answer 的 type 判别值
for cls in (BinaryAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer):
    tf = cls.model_fields.get("type")
    print(cls.__name__, "type:", tf.annotation if tf else "?")
