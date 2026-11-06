import inspect
from agentscope.classifier._question import BinaryQuestion, BinaryCriteria, ChoiceQuestion
print("BinaryCriteria:", inspect.signature(BinaryCriteria.__init__))
print("fields:", list(BinaryCriteria.model_fields))
print()
src = inspect.getsource(BinaryCriteria)
print(src[:600])
