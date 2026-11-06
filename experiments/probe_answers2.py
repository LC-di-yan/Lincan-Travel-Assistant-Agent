import dataclasses
from agentscope.classifier._response import BinaryAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer
for cls in (BinaryAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer):
    print(cls.__name__, "fields:", [f.name for f in dataclasses.fields(cls)] if dataclasses.is_dataclass(cls) else "not dataclass")
    if dataclasses.is_dataclass(cls):
        print("   types:", [(f.name, str(f.type)[:40]) for f in dataclasses.fields(cls)])
