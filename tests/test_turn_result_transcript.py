import json
from types import SimpleNamespace

from server.utils.conversation_transcript import Transcript


def test_partial_snapshot_and_late_events_preserve_first_terminal():
    transcript = Transcript()
    def observe(kind, data):
        transcript.observe({"event": kind, "data": json.dumps(data)})
    def row(node, value):
        return {"node_id": node, "agent_name": "memory_query", "status": "success",
                "data": {"answer": value, "headers": {"Authorization": "not-for-history"}}}
    for item in (row("out", "旧"), row("back", "返"), row("out", "去")):
        observe("agent_result", item)
    observe("complete", {"results": [row("back", "新返")]})
    observe("error", {"message": "迟到的错误"})
    observe("agent_result", row("late", "迟到"))
    _, record = transcript.assistant_message(SimpleNamespace())
    assert record["status"] == "complete"
    assert [r["data"] for r in record["results"]] == [{"answer": "去"}, {"answer": "新返"}]


def test_interrupted_anonymous_calls_are_not_silently_deduplicated():
    transcript = Transcript()
    for n in range(2):
        transcript.observe({"event": "agent_result", "data": json.dumps({"agent_name": "memory_query", "data": {"answer": str(n)}})})
    _, record = transcript.assistant_message(SimpleNamespace())
    assert record["status"] == "interrupted"
    assert len(record["results"]) == 2
