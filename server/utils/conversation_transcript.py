"""SSE 的持久展示投影与同一会话的恢复点。"""
import json
import math
import re
import time

from pydantic import ValidationError

from context.conversation_archive import redact_private_text
from server.personal.models import Event, PlanRef
from server.utils.assistant_summary import build_assistant_summary
from server.utils.list_expander import LIST_AGENTS, LIST_RESULT_TTL
from utils.trip_request import TripRequest

PENDING_TTL_SEC = 300.0
TERMINALS = {"complete", "clarification", "error"}
_RESULT_FIELDS = {"agent_name", "priority", "status", "data", "node_id", "label", "node_status", "cached"}
_PRIVATE_FIELDS = {
    "apikey", "xapikey", "token", "bearertoken", "confirmationtoken", "confirmationcommand", "operationtoken",
    "operationid", "csrf", "csrftoken", "cookie", "cookies",
    "authorization", "accesstoken", "secret", "clientsecret", "secretkey", "password", "sessionid", "userid",
    "headers", "rawresponse", "rawrequest", "rawcontent", "debug", "traceback", "trace", "prompt",
    "reasoningcontent", "idempotencykey", "candidatebase", "candidatebaserevision", "candidateref", "candidatesessionid",
}
_PENDING_FIELDS = {
    "intents", "agent_schedule", "original_query", "rewritten_query", "fast_event", "fast_train_ticket",
    "key_entities", "clarification_field", "clarification_question", "needs_clarification",
}
_FOCUS_FIELDS = ("focus_city", "last_search_city", "current_trip_destination")
_RENDER_LIMIT = 72 * 1024
_CHECKPOINT_LIMIT = 36 * 1024


def _trim(value, depth=0):
    if isinstance(value, (type(None), bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return redact_private_text(value)[:8000]
    if depth >= 15:
        return None
    if isinstance(value, list):
        return [_trim(item, depth + 1) for item in value[:80]]
    if isinstance(value, dict):
        return {
            key: _trim(item, depth + 1)
            for key, item in value.items()
            if isinstance(key, str) and len(key) <= 100 and re.sub(r"[^a-z0-9]", "", key.lower()) not in _PRIVATE_FIELDS
        }
    return None


def _bytes(obj):
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _display_results(values):
    output, size = [], 2
    for row in values[:24]:
        if not isinstance(row, dict) or not isinstance(row.get("agent_name"), str) or not isinstance(row.get("data"), dict):
            continue
        public = _trim({key: value for key, value in row.items() if key in _RESULT_FIELDS})
        item_size = _bytes(public) + 1
        if size + item_size > _RENDER_LIMIT:
            continue
        size += item_size
        output.append(public)
    return output


def _payload(chunk):
    value = json.loads(chunk["data"])
    return value if isinstance(value, dict) else {}


def _merge_results(observed, incoming, *, snapshot=False):
    """Keep stable node positions within the existing transcript display limit."""
    rows = list(observed)
    occurrences = {}
    for row in incoming[:24]:
        if not isinstance(row, dict) or not isinstance(row.get("agent_name"), str) or not isinstance(row.get("data"), dict):
            continue
        node, name = row.get("node_id"), row["agent_name"]
        index = None
        if isinstance(node, str) and node:
            index = next((i for i, old in enumerate(rows) if old.get("node_id") == node), None)
        elif snapshot:
            matches = [i for i, old in enumerate(rows) if not old.get("node_id") and old.get("agent_name") == name]
            n = occurrences.get(name, 0)
            index = matches[n] if n < len(matches) else None
            occurrences[name] = n + 1
        if index is not None:
            rows[index] = row
        elif len(rows) < 24:
            rows.append(row)
    return rows


class Transcript:
    def __init__(self):
        self.partial = []
        self.terminal = None

    def observe(self, chunk):
        if self.terminal is not None:
            return
        event = chunk.get("event")
        if event in TERMINALS:
            self.terminal = (event, _payload(chunk))
        elif event == "agent_result":
            self.partial = _merge_results(self.partial, [_payload(chunk)])

    def assistant_message(self, session):
        status, payload = self.terminal or ("interrupted", {})
        snapshot = payload.get("results") if status in {"complete", "error"} else None
        results = _merge_results(self.partial, snapshot, snapshot=True) if isinstance(snapshot, list) else self.partial
        visible = _display_results(results)
        if status == "complete":
            # Some integrations return unexpected field types. A summary failure
            # must still preserve the displayed result and never swallow the SSE.
            try:
                text = build_assistant_summary({"results": results})
            except (TypeError, ValueError, AttributeError):
                text = "本轮已返回处理结果，详细内容可见结果区。"
        elif status == "clarification":
            text = payload.get("question") or "请补充本轮信息。"
        elif status == "error":
            text = payload.get("message") or "这轮回答未完成，请重试。"
        else:
            text = "这轮生成已停止，已收到的部分结果仍可查看。" if visible else "这轮生成未完成，已发送的消息已保留。"
        presentation = {"status": status}
        if visible:
            presentation["results"] = visible
        checkpoint = capture_checkpoint(session)
        if checkpoint:
            presentation["checkpoint"] = checkpoint
        return redact_private_text(str(text))[:16000], presentation


def capture_checkpoint(session):
    pending = getattr(session, "pending_intention", None)
    checkpoint = {}
    if isinstance(pending, dict):
        remaining = PENDING_TTL_SEC - (time.monotonic() - getattr(session, "pending_since", 0.0))
        if remaining > 0:
            checkpoint["pending"] = _trim({key: value for key, value in pending.items() if key in _PENDING_FIELDS})
            checkpoint["pending_until"] = time.time() + min(remaining, PENDING_TTL_SEC)
    if isinstance(trip := getattr(session, "trip_request", None), TripRequest):
        checkpoint["trip_request"] = _trim(trip.model_dump(mode="json"))
        if isinstance(ref := getattr(session, "trip_plan_ref", None), PlanRef):
            checkpoint["plan_ref"] = ref.model_dump(mode="json")
            checkpoint["plan_revision"] = getattr(session, "trip_plan_revision", None)
            carry = getattr(session, "trip_carry_items", [])
            checkpoint["carry_items"] = _trim([event.model_dump(mode="json") for event in carry[:20] if isinstance(event, Event)])
    focus = getattr(session, "focus_state", None)
    for key in _FOCUS_FIELDS:
        value = getattr(focus, key, None)
        if isinstance(value, str) and 0 < len(value) <= 32:
            checkpoint.setdefault("focus", {})[key] = redact_private_text(value)
    recent_list = getattr(focus, "last_list_result", None)
    if _fresh_list(recent_list):
        checkpoint["recent_list"] = _trim(recent_list)
    if _bytes(checkpoint) > _CHECKPOINT_LIMIT:
        checkpoint.pop("recent_list", None)
    if _bytes(checkpoint) > _CHECKPOINT_LIMIT:
        checkpoint.pop("carry_items", None)
    return checkpoint if _bytes(checkpoint) <= _CHECKPOINT_LIMIT else {}


def _fresh_list(value):
    return (isinstance(value, dict) and value.get("agent") in LIST_AGENTS and isinstance(value.get("data"), dict)
            and type(value.get("ts")) in (int, float) and 0 <= time.time() - value["ts"] < LIST_RESULT_TTL)


def restore_checkpoint(session, checkpoint):
    if not isinstance(checkpoint, dict):
        return
    if isinstance(pending := checkpoint.get("pending"), dict):
        until = checkpoint.get("pending_until")
        if type(until) in (int, float):
            remaining = until - time.time()
            if 0 < remaining <= PENDING_TTL_SEC:
                session.pending_intention = pending
                session.pending_since = time.monotonic() - (PENDING_TTL_SEC - remaining)
    try:
        if checkpoint.get("trip_request"):
            session.trip_request = TripRequest.model_validate(checkpoint["trip_request"])
            if checkpoint.get("plan_ref"):
                session.trip_plan_ref = PlanRef.model_validate(checkpoint["plan_ref"])
                revision = checkpoint.get("plan_revision")
                session.trip_plan_revision = revision if isinstance(revision, int) and revision > 0 else None
                session.trip_carry_items = [Event.model_validate(item) for item in checkpoint.get("carry_items", [])[:20]]
    except (ValidationError, TypeError):
        # Old or unsupported checkpoints must not prevent continuing a conversation.
        session.trip_request = None
        session.trip_plan_ref = None
        session.trip_plan_revision = None
        session.trip_carry_items = []
    if isinstance(focus := checkpoint.get("focus"), dict):
        for key in _FOCUS_FIELDS:
            if isinstance(value := focus.get(key), str) and 0 < len(value) <= 32:
                setattr(session.focus_state, key, value)
    if _fresh_list(value := checkpoint.get("recent_list")):
        session.focus_state.last_list_result = value
