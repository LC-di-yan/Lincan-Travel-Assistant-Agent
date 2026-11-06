from agentscope.classifier._question import BinaryQuestion, ChoiceQuestion, ScoreQuestion
import json
print("BinaryQuestion.criteria:", BinaryQuestion.model_fields["criteria"].annotation)
print("ChoiceQuestion.criteria:", ChoiceQuestion.model_fields["criteria"].annotation)
print()
# 用 agentscope 的字面量构造（binary 而非 noul）
bq = BinaryQuestion(instructions="test", criteria={"ok": "yes"})
print("BinaryQuestion dump:", bq.model_dump(exclude_unset=True))
cq = ChoiceQuestion(instructions="pick", criteria={"a": "A", "b": "B"})
print("ChoiceQuestion dump:", json.dumps(cq.model_dump(exclude_unset=True), ensure_ascii=False)[:200])
print()
# 判别联合接受 binary dict？
from typing import Annotated, get_args
import agentscope.classifier._question as Q
print("all question classes:", [c for c in dir(Q) if c.endswith("Question")])
