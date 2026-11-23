"""用户级聊天记录的分组与只读展示。"""
from datetime import datetime
import re
from zoneinfo import ZoneInfo

LEGACY_CONVERSATION = "~legacy"
_SESSION = re.compile(r"^[\w-]{1,32}$")
_VISIBLE_ROLES = ("user", "assistant")
_TZ = ZoneInfo("Asia/Shanghai")
_CONFIRMATION_TEXT = re.compile(r"确认费用\s+[0-9a-f]{24}\b", re.IGNORECASE)
_CREDENTIAL_TEXT = re.compile(r"(?i)(?:\bsk-[A-Za-z\d_-]{16,}|([?&](?:key|api[_-]?key|token|access_token|signature)=)[^\s&#]+)")


def redact_private_text(text):
    value = _CONFIRMATION_TEXT.sub("确认费用操作", text)
    return _CREDENTIAL_TEXT.sub(lambda match: (match.group(1) or "") + "[已隐藏]", value)


def conversation_id(value):
    return value if isinstance(value, str) and _SESSION.fullmatch(value) else LEGACY_CONVERSATION


def timestamp_string(value):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return (stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=_TZ)).isoformat()


def compact_line(value, max_length):
    return " ".join(redact_private_text(str(value or "")).split())[:max_length]


def _visible(record):
    return isinstance(record, dict) and record.get("role") in _VISIBLE_ROLES and isinstance(record.get("content"), str)


def list_json_messages(records, query, before, limit):
    sessions = {}
    keyword = query.casefold() if query else None
    for index, row in enumerate(records, 1):
        if not _visible(row):
            continue
        current = conversation_id(row.get("session_id"))
        summary = sessions.setdefault(current, {
            "id": current, "first_user": "", "created_at": row.get("timestamp"),
            "count": 0, "found": not keyword,
        })
        if row.get("role") == "user" and not summary["first_user"]:
            summary["first_user"] = compact_line(row["content"], 96)
        if keyword and not summary["found"]:
            summary["found"] = keyword in row["content"].casefold()
        summary.update(cursor=index, updated_at=row.get("timestamp"), preview=compact_line(row["content"], 144))
        summary["count"] += 1
    rows = sorted((item for item in sessions.values() if item["found"] and (before is None or item["cursor"] < before)),
                  key=lambda item: item["cursor"], reverse=True)
    return session_list(rows[:limit + 1], limit)


def session_list(rows, limit):
    items = []
    for row in rows[:limit]:
        legacy = row["id"] == LEGACY_CONVERSATION
        title = "早期对话记录" if legacy else compact_line(row.get("first_user"), 48) or "未命名对话"
        items.append({
            "id": row["id"], "title": title, "preview": compact_line(row.get("preview"), 100),
            "created_at": timestamp_string(row.get("created_at")),
            "updated_at": timestamp_string(row.get("updated_at")),
            "message_count": row["count"], "readonly": legacy,
        })
    return {"items": items, "next_before": rows[limit - 1]["cursor"] if len(rows) > limit else None}


def read_json_messages(records, scope, before, limit, *, check_exists=True):
    matched = []
    exists = False
    for index in range(len(records), 0, -1):
        row = records[index - 1]
        if not _visible(row) or conversation_id(row.get("session_id")) != scope:
            continue
        exists = True
        if (before is None or index < before) and len(matched) < limit + 1:
            matched.append({**row, "cursor": index})
        if len(matched) > limit:
            break
    if not exists and check_exists:
        return None
    return session_page(matched, limit)


def session_page(rows, limit):
    return {
        "rows": list(reversed(rows[:limit])),
        "next_before": rows[limit - 1]["cursor"] if len(rows) > limit else None,
    }


def public_message(row):
    presentation = row.get("presentation")
    presentation = presentation if isinstance(presentation, dict) else {}
    return {
        "id": str(row["cursor"]),
        "role": row["role"],
        "content": redact_private_text(row["content"]),
        "timestamp": timestamp_string(row.get("timestamp")),
        **({"status": presentation["status"]} if "status" in presentation else {}),
        **({"results": presentation["results"]} if isinstance(presentation.get("results"), list) else {}),
    }
