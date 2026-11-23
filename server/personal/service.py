"""个人计划的版本化写入、幂等回执及本人读取。"""
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from server.personal.candidates import candidates, from_summary
from server.personal.conflicts import RULE_VERSION, Schedule, evaluate, project, quote_expiry
from server.personal.models import (CandidateInput, CopyInput, Event, ManualInput, OperationPreview, PlanRef, PlanSnapshot,
                                    RestoreInput, SelectSavedOption, SummaryInput)
from utils.trip_request import TripBudget, TripRequest

_TZ = ZoneInfo("Asia/Shanghai")
_MAX_PLANS = 200
_MAX_VERSIONS = 60
_MAX_OPERATIONS = 800


class PersonalError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def _now():
    return datetime.now(UTC)


def _absent():
    return PersonalError(404, "not_found", "找不到这条个人行程或版本。")


def _plan(data, plan_id):
    if plan_id not in data.plans:
        raise _absent()
    return data.plans[plan_id]


def _version(data, plan_id, version):
    _plan(data, plan_id)
    result = data.versions.get(plan_id, {}).get(str(version))
    if not result:
        raise _absent()
    return result


def _cas(plan, revision):
    if plan["revision"] != revision:
        raise PersonalError(412, "revision_changed", "行程已在另一处修改，请查看当前版本后再试。",
                            {"revision": plan["revision"]})


def _active(plan):
    if plan["lifecycle"] in {"archived", "cancelled", "superseded", "completed"}:
        raise PersonalError(409, "not_editable", "此行程只能查看，复制为新草稿后可继续编辑。")


def _slug_payload(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _idempotent(data, action, key, fingerprint, apply):
    now = _now()
    _prune_operations(data, now)
    op_key = f"{action}:{key}"
    if previous := data.operations.get(op_key):
        if previous["fingerprint"] != fingerprint:
            raise PersonalError(409, "idempotency_mismatch", "同一个提交编号不能用于不同的操作。")
        return previous["result"]
    if len(data.operations) >= _MAX_OPERATIONS:
        raise PersonalError(429, "too_many_operations", "操作过于频繁，请稍后再试。")
    receipt = apply()
    data.operations[op_key] = {"result": receipt, "expires_at": (now + timedelta(days=2)).isoformat(),
                               "fingerprint": fingerprint}
    return receipt


def _prune_operations(data, now):
    for item in tuple(data.operations):
        if datetime.fromisoformat(data.operations[item]["expires_at"]) <= now:
            del data.operations[item]


def _schedule_summary(plan):
    return {"plan_id": plan["plan_id"], "title": plan["title"], "version": plan["scheduled_version"],
            "revision": plan["revision"], "lifecycle": plan["lifecycle"]}


def _schedule_target(plan, action, draft_version):
    if action in {"schedule", "replace"} and plan["lifecycle"] != "draft":
        raise PersonalError(409, "not_draft", "只有草稿可以首次安排或替换另一条行程。")
    if action in {"reschedule", "cancel", "complete"} and plan["lifecycle"] != "scheduled":
        raise PersonalError(409, "not_scheduled", "此行程目前不是已安排状态。")
    if action == "reschedule" and plan["scheduled_version"] == draft_version:
        raise PersonalError(409, "already_scheduled", "此版本已经安排，请先生成新的草稿版本。")
    if action == "archive" and plan["lifecycle"] == "archived":
        raise PersonalError(409, "already_archived", "此行程已归档。")
    expected = plan["current_draft_version"] if action not in {"cancel", "complete"} else plan["scheduled_version"]
    if expected != draft_version:
        raise PersonalError(409, "draft_changed", "请先查看现在的草稿或已安排版本，再重新预检。")


def _scheduled_set(data, excluded):
    return [Schedule(key, obj["version"], data.plans[key]["title"],
                     tuple(Event.model_validate(item) for item in obj["events"]))
            for key, obj in data.schedule.items() if key in data.plans and key not in excluded
            and data.plans[key]["lifecycle"] == "scheduled"]


def _preview(data, plan_id, preview: OperationPreview, now):
    plan = _plan(data, plan_id)
    _cas(plan, preview.expected_revision)
    _schedule_target(plan, preview.action, preview.draft_version)
    snapshot = PlanSnapshot.model_validate(_version(data, plan_id, preview.draft_version)["snapshot"])
    replacement_plans = []
    for ref in preview.replace_refs:
        replacement = _plan(data, str(ref.plan_id))
        if replacement is plan or replacement["lifecycle"] != "scheduled" or replacement["scheduled_version"] != ref.version:
            raise PersonalError(409, "replacement_changed", "被替换的具体已安排行程或版本已变动。")
        _cas(replacement, ref.revision)
        replacement_plans.append(replacement)
    calendar_revision = data.state.get("calendar_revision", 0)
    projection, quote_valid_until = None, None
    if preview.action in {"schedule", "replace", "reschedule"}:
        projection = project(plan_id, preview.draft_version, plan["title"], snapshot)
        exclude = {item["plan_id"] for item in replacement_plans} | {plan_id}
        report = evaluate(projection, _scheduled_set(data, exclude), snapshot=snapshot, now=now, calendar_revision=calendar_revision)
        quote_valid_until, had_stale = quote_expiry(snapshot, now)
        if had_stale:
            report["issues"].append({
                "id": uuid5(UUID(plan_id), f"stale-quote:{preview.draft_version}").hex,
                "code": "quote_expired", "severity": "potential",
                "message": "已选方案含过期报价；只能安排日历，不能确认旧价格仍有效或座席仍可用。",
                "requires_ack": True, "blocks_schedule": False, "event_ref": None, "window": None, "other": None,
            })
    else:
        report = {"rule_version": RULE_VERSION, "calendar_revision": calendar_revision, "issues": [], "can_commit": True}
    return plan, replacement_plans, snapshot, projection, report, quote_valid_until


def _close_out(data, plan, lifecycle, now, *, superseded_by=None):
    key = plan["plan_id"]
    if plan.get("scheduled_version"):
        plan["last_scheduled_version"] = plan["scheduled_version"]
    plan.update(scheduled_version=None, lifecycle=lifecycle, updated_at=now.isoformat(), revision=plan["revision"] + 1)
    timestamp = {"completed": "completed_at", "cancelled": "cancelled_at", "archived": "archived_at",
                 "superseded": "superseded_at"}[lifecycle]
    plan[timestamp] = now.isoformat()
    data.schedule.pop(key, None)
    if superseded_by:
        plan["superseded_by"] = superseded_by


def _version_data(snapshot: PlanSnapshot, version: int, parent: int | None, now):
    rendered = snapshot.model_dump_json()
    if len(rendered.encode("utf-8")) > 256 * 1024:
        raise PersonalError(422, "snapshot_too_large", "行程内容过多，请减少活动后重试。")
    return {"version": version, "parent_version": parent, "created_at": now.isoformat(),
            "snapshot": json.loads(rendered)}


def _copy_schedule(snapshot, plan_id, preserve=()):
    namespace = UUID(plan_id)

    def identify(items):
        result = []
        for item in items:
            if item.event_id in preserve:
                result.append(item)
                continue
            identity = str(item.event_id)
            if snapshot.source_kind == "typed":
                if item.kind == "rail":
                    identity = "typed:outbound" if item.city == snapshot.origin else "typed:inbound"
                elif item.kind in {"meeting", "check_in", "check_out"}:
                    trip_id = snapshot.trip_request.trip_id if snapshot.trip_request else None
                    generated = uuid5(NAMESPACE_URL, f"aligo:{trip_id}:{item.kind}") if trip_id else None
                    if generated == item.event_id:
                        identity = f"typed:{item.kind}"
            result.append(item.model_copy(update={"event_id": uuid5(namespace, identity)}))
        return result

    return snapshot.model_copy(update={
        "schedule_items": identify(snapshot.schedule_items),
        "options": [item.model_copy(update={"schedule_items": identify(item.schedule_items)}) for item in snapshot.options],
    })


def _content(data, user_id, payload, expected_base=None, expected_revision=None, import_legacy=False, cache=candidates) -> PlanSnapshot:
    if isinstance(payload, CandidateInput):
        snapshot = cache.get(user_id, payload.session_id, payload.candidate_ref)
        if snapshot is None:
            raise PersonalError(404, "candidate_unavailable", "找不到可保存的本轮结果，可能已过期。请重新生成。")
        if expected_base is not None and snapshot.based_on != expected_base:
            raise PersonalError(409, "candidate_base_mismatch", "此结果不是基于你选择的行程版本生成的。")
        if expected_revision is not None and snapshot.base_revision != expected_revision:
            raise PersonalError(412, "candidate_outdated", "生成本方案后行程已变更，请重新规划或另存草稿。")
        option_id = payload.option_id if payload.option_id is not None else snapshot.selected_option_id
        if option_id is not None and option_id not in {row.option_id for row in snapshot.options}:
            raise PersonalError(422, "unknown_option", "所选候选不属于本轮结果。")
        return snapshot.model_copy(update={"title": payload.title or snapshot.title, "selected_option_id": option_id})
    if isinstance(payload, ManualInput):
        return PlanSnapshot(**payload.draft.model_dump(), source_kind="manual", quality="manual",
                            based_on=expected_base, base_revision=expected_revision)
    if isinstance(payload, SummaryInput) and import_legacy:
        if len(data.matching_history) != 1:
            if data.matching_history:
                raise PersonalError(409, "ambiguous_history", "旧记录编号重复，请手工创建草稿。")
            raise _absent()
        return from_summary(data.matching_history[0])
    if isinstance(payload, CopyInput) and import_legacy:
        original = PlanSnapshot.model_validate(_version(data, str(payload.ref.plan_id), payload.ref.version)["snapshot"])
        return original.model_copy(update={"title": payload.title or original.title, "based_on": payload.ref,
                                          "base_revision": _plan(data, str(payload.ref.plan_id))["revision"]})
    raise PersonalError(422, "unsupported_source", "不支持这一行程来源。")


def _summary_fields(snapshot):
    return {
        "origin": snapshot.origin, "destination": snapshot.destination, "quality": snapshot.quality,
        "start_date": snapshot.start_date.isoformat() if snapshot.start_date else None,
        "end_date": snapshot.end_date.isoformat() if snapshot.end_date else None,
    }


def _projected_dates(snapshot, schedule):
    starts = [snapshot.start_date] if snapshot.start_date else []
    ends = [snapshot.end_date or snapshot.start_date] if snapshot.start_date else []
    for event in schedule.blocks:
        if event.start_at and event.end_at:
            starts.append(event.start_at.astimezone(_TZ).date())
            ends.append(event.end_at.astimezone(_TZ).date())
        elif event.local_date:
            starts.append(event.local_date)
            ends.append(event.end_date or event.local_date)
    return min(starts).isoformat() if starts else None, max(ends).isoformat() if ends else None


class Trips:
    def __init__(self, repository, *, cache=candidates):
        self.repository = repository
        self.user_id = repository.user_id
        self.cache = cache

    async def list(self, *, status=None, search=None, cursor=None, limit=30, start_date=None, end_date=None):
        def read(data):
            items = sorted(data.plans.values(), key=lambda item: (item["updated_at"], item["plan_id"]), reverse=True)
            if status:
                items = [item for item in items if item["lifecycle"] == status]
            else:
                items = [item for item in items if item["lifecycle"] != "archived"]
            if search:
                needle = search.casefold()
                items = [item for item in items if needle in " ".join(
                    str(item.get(field) or "") for field in ("title", "origin", "destination")
                ).casefold()]
            if start_date:
                items = [item for item in items if (item.get("end_date") or item.get("start_date") or "") >= start_date.isoformat()]
            if end_date:
                items = [item for item in items if item.get("start_date") and item["start_date"] <= end_date.isoformat()]
            if cursor:
                items = [item for item in items if (item["updated_at"], item["plan_id"]) < cursor]
            page = items[:limit]
            return {"items": page, "next_cursor": (page[-1]["updated_at"], page[-1]["plan_id"]) if len(items) > limit else None}

        return await self.repository.run(read)

    async def overview(self):
        def read(data):
            today = _now().astimezone(_TZ).date().isoformat()
            rows = list(data.plans.values())
            current = sorted([row for row in rows if row["lifecycle"] == "scheduled" and
                              (row.get("scheduled_end_date") or row.get("start_date") or "") >= today],
                             key=lambda row: row.get("scheduled_start_date") or row.get("start_date") or "")
            drafts = sorted([row for row in rows if row["lifecycle"] == "draft"], key=lambda row: row["updated_at"], reverse=True)
            completed_cities = {}
            for row in rows:
                if row.get("completed_at") and (row["completed_at"][:10] >= (date.fromisoformat(today) - timedelta(days=365)).isoformat()):
                    city = row.get("last_scheduled_destination")
                    if city:
                        completed_cities[city] = completed_cities.get(city, 0) + 1
            cities = [{"city": city, "count": count} for city, count in sorted(completed_cities.items(), key=lambda pair: (-pair[1], pair[0]))[:5]]
            return {"today": today, "upcoming": current[:5], "recent_drafts": drafts[:5], "frequent_destinations": cities,
                    "counts": {"scheduled": len(current), "draft": len(drafts)}}
        return await self.repository.run(read)

    async def legacy(self):
        def read(data):
            rows = []
            for item in data.recent_history:
                snapshot = from_summary(item)
                rows.append({"trip_id": item["trip_id"], "ambiguous": item["ambiguous"],
                             **_summary_fields(snapshot), "purpose": snapshot.notes})
            return {"items": rows}

        return await self.repository.run(read, recent_history=True)

    async def get(self, plan_id):
        key = str(plan_id)

        def read(data):
            plan = _plan(data, key)
            return {"plan": plan, "draft": _version(data, key, plan["current_draft_version"]),
                    "scheduled": _version(data, key, plan["scheduled_version"]) if plan.get("scheduled_version") else None}

        return await self.repository.run(read, version_ids=(key,))

    async def version(self, plan_id, number):
        key = str(plan_id)
        return await self.repository.run(lambda data: _version(data, key, number), version_ids=(key,))

    async def versions(self, plan_id):
        key = str(plan_id)

        def read(data):
            _plan(data, key)
            return {"items": [{k: v for k, v in item.items() if k != "snapshot"}
                              for item in sorted(data.versions.get(key, {}).values(), key=lambda v: v["version"], reverse=True)]}
        return await self.repository.run(read, version_ids=(key,))

    async def create(self, payload, idempotency_key):
        fingerprint = _slug_payload(payload.model_dump(mode="json", exclude_unset=True))

        def create(data):
            def apply():
                if len(data.plans) >= _MAX_PLANS:
                    raise PersonalError(429, "trip_limit", "已达到存储上限，暂不能保存更多行程。")
                key, now = str(uuid4()), _now()
                snapshot = _content(data, self.user_id, payload, import_legacy=True, cache=self.cache)
                snapshot = _copy_schedule(snapshot, key)
                plan = {"plan_id": key, "title": snapshot.title, "lifecycle": "draft", "revision": 1,
                        "current_draft_version": 1, "scheduled_version": None, "created_at": now.isoformat(),
                        "updated_at": now.isoformat(), **_summary_fields(snapshot)}
                data.plans[key] = plan
                data.versions[key] = {"1": _version_data(snapshot, 1, None, now)}
                return {"plan_id": key, "version": 1, "revision": 1, "lifecycle": "draft"}
            return _idempotent(data, "create", idempotency_key, fingerprint, apply)

        return await self.repository.run(
            create, write=True,
            history_id=payload.trip_id if isinstance(payload, SummaryInput) else None,
            version_ids=(str(payload.ref.plan_id),) if isinstance(payload, CopyInput) else (),
        )

    async def add_version(self, plan_id, payload, revision, idempotency_key):
        key = str(plan_id)
        fingerprint = _slug_payload(key, revision, payload.model_dump(mode="json", exclude_unset=True))

        def append(data):
            def apply():
                plan = _plan(data, key)
                _cas(plan, revision)
                _active(plan)
                base_version = _version(data, key, payload.based_on_version)
                base = PlanRef(plan_id=plan_id, version=payload.based_on_version)
                if isinstance(payload.content, (RestoreInput, SelectSavedOption)):
                    old = PlanSnapshot.model_validate(base_version["snapshot"])
                    changes = {"based_on": base, "base_revision": revision}
                    if isinstance(payload.content, SelectSavedOption):
                        if payload.content.option_id not in {option.option_id for option in old.options}:
                            raise PersonalError(422, "unknown_option", "所选备选不属于这个行程版本。")
                        changes["selected_option_id"] = payload.content.option_id
                    snapshot = old.model_copy(update=changes)
                else:
                    snapshot = _content(data, self.user_id, payload.content, expected_base=base,
                                        expected_revision=revision, cache=self.cache)
                if isinstance(payload.content, CandidateInput):
                    existing = PlanSnapshot.model_validate(base_version["snapshot"])
                    snapshot = _copy_schedule(snapshot, key, {item.event_id for item in existing.schedule_items})
                if not isinstance(payload.content, ManualInput) and not (isinstance(payload.content, CandidateInput) and payload.content.title):
                    snapshot = snapshot.model_copy(update={"title": plan["title"]})
                number = max(map(int, data.versions[key])) + 1
                if number > _MAX_VERSIONS:
                    raise PersonalError(429, "version_limit", "此行程版本已满，可另存为新计划。")
                now = _now()
                data.versions[key][str(number)] = _version_data(snapshot, number, payload.based_on_version, now)
                plan.update(title=snapshot.title, current_draft_version=number, revision=revision + 1, updated_at=now.isoformat(),
                            **_summary_fields(snapshot))
                return {"plan_id": key, "version": number, "revision": plan["revision"], "lifecycle": plan["lifecycle"]}
            return _idempotent(data, "append", idempotency_key, fingerprint, apply)

        return await self.repository.run(append, write=True, version_ids=(key,))

    async def rename(self, plan_id, title, revision):
        key = str(plan_id)

        def apply(data):
            plan = _plan(data, key)
            _cas(plan, revision)
            _active(plan)
            plan.update(title=title, revision=revision + 1, updated_at=_now().isoformat())
            return plan

        return await self.repository.run(apply, write=True)

    async def preview(self, plan_id, payload: OperationPreview):
        key = str(plan_id)

        def apply(data):
            now = _now()
            plan, replacements, _, _, report, quote_valid_until = _preview(data, key, payload, now)
            for issue in report["issues"]:
                if issue.get("other"):
                    issue["other"]["revision"] = data.plans[issue["other"]["plan_id"]]["revision"]
            result = {"action": payload.action, "operation_id": None, "expires_at": None, "report": report,
                      "plan": _schedule_summary(plan), "replacements": [_schedule_summary(item) for item in replacements]}
            if not report["can_commit"]:
                return result
            _prune_operations(data, now)
            if len(data.operations) >= _MAX_OPERATIONS:
                raise PersonalError(429, "too_many_operations", "预检过于频繁，请稍后再试。")
            until = min(now + timedelta(minutes=10), quote_valid_until or now + timedelta(minutes=10))
            identifier = str(uuid4())
            op_code = f"preview:{identifier}"
            data.operations[op_code] = {
                "request": payload.model_dump(mode="json"), "plan_id": key,
                "calendar_revision": report["calendar_revision"], "rule_version": report["rule_version"],
                "acknowledgements": sorted(item["id"] for item in report["issues"] if item["requires_ack"]),
                "expires_at": until.isoformat(), "used": False,
            }
            return dict(result, operation_id=identifier, expires_at=until.isoformat())

        return await self.repository.run(apply, write=True, version_ids=(key,), schedule=True)

    async def commit(self, plan_id, payload, idempotency_key):
        key = str(plan_id)
        fingerprint = _slug_payload(key, str(payload.operation_id), sorted(set(payload.acknowledged_issue_ids)), payload.confirmed)

        def commit(data):
            def perform():
                _plan(data, key)
                operation = data.operations.get(f"preview:{payload.operation_id}")
                if not operation or operation["plan_id"] != key:
                    raise PersonalError(410, "preview_expired", "预检已过期或不可用，请重新预检。")
                if operation["used"]:
                    raise PersonalError(409, "preview_used", "这项预检已经确认，不能再次提交。")
                now = _now()
                if datetime.fromisoformat(operation["expires_at"]) <= now:
                    raise PersonalError(410, "preview_expired", "预检或报价已过期，请重新预检。")
                if operation["calendar_revision"] != data.state.get("calendar_revision", 0) or operation["rule_version"] != RULE_VERSION:
                    raise PersonalError(409, "calendar_changed", "安排期间日历已变更，请重新预检。")
                preview = OperationPreview.model_validate(operation["request"])
                plan, replacements, snapshot, projection, report, _ = _preview(data, key, preview, now)
                warnings = sorted(item["id"] for item in report["issues"] if item["requires_ack"])
                if not report["can_commit"] or warnings != operation["acknowledgements"]:
                    raise PersonalError(409, "report_changed", "冲突或证据有变化，请重新预检。")
                if sorted(set(payload.acknowledged_issue_ids)) != warnings:
                    raise PersonalError(422, "review_required", "请先逐项核对并确认所有已提示风险。")
                if projection:
                    for old in replacements:
                        _close_out(data, old, "superseded", now, superseded_by=key)
                    start_day, end_day = _projected_dates(snapshot, projection)
                    plan.update(scheduled_version=projection.version, lifecycle="scheduled",
                                updated_at=now.isoformat(), revision=plan["revision"] + 1,
                                last_scheduled_destination=snapshot.destination,
                                scheduled_start_date=start_day, scheduled_end_date=end_day)
                    data.schedule[key] = {"version": projection.version,
                                          "events": [item.model_dump(mode="json") for item in projection.blocks]}
                else:
                    _close_out(data, plan, {"cancel": "cancelled", "archive": "archived", "complete": "completed"}[preview.action], now)
                operation["used"] = True
                data.state["calendar_revision"] = data.state.get("calendar_revision", 0) + 1
                return {"plan_id": key, "version": preview.draft_version, "revision": plan["revision"],
                        "lifecycle": plan["lifecycle"], "calendar_revision": data.state["calendar_revision"]}
            return _idempotent(data, "schedule_commit", idempotency_key, fingerprint, perform)

        return await self.repository.run(commit, write=True, version_ids=(key,), schedule=True)

    async def candidate_conflicts(self, snapshot: PlanSnapshot):
        # An unsaved candidate has no authenticated durable identity; exclude a
        # referenced plan only for this advisory calculation, never for a write.
        def read(data):
            identifier = str(snapshot.based_on.plan_id) if snapshot.based_on else str(uuid4())
            version = data.plans.get(identifier, {}).get("current_draft_version", 0) + 1
            return evaluate(project(identifier, version, snapshot.title, snapshot), _scheduled_set(data, {identifier}),
                            snapshot=snapshot, now=_now(), calendar_revision=data.state.get("calendar_revision", 0))
        return await self.repository.run(read, schedule=True)

    async def trip_context(self, ref):
        request, _, _ = await self.open_trip_context(ref)
        return request

    async def open_trip_context(self, ref):
        key = str(ref.plan_id)
        version, revision = await self.repository.run(
            lambda data: (_version(data, key, ref.version), _plan(data, key)["revision"]), version_ids=(key,),
        )
        snapshot = PlanSnapshot.model_validate(version["snapshot"])
        keep = [event for event in snapshot.schedule_items if event.kind not in {"rail", "flight", "check_in", "check_out"}]
        # A fresh session identity distinguishes this fixed base from any previous task.
        trip_id = uuid5(ref.plan_id, str(ref.version)).hex
        if snapshot.trip_request:
            keep = [event for event in keep if event.event_id != uuid5(ref.plan_id, "typed:meeting")]
            return snapshot.trip_request.model_copy(update={"trip_id": trip_id}), revision, keep
        currency = snapshot.budget.currency if snapshot.budget else None
        budget = TripBudget(amount=snapshot.budget.amount, currency=currency) if currency in {"CNY", "USD", "EUR", "HKD", "JPY"} else None
        meeting = next((event for event in keep if event.kind == "meeting" and event.commitment == "fixed"), None)
        meeting_args = {}
        if meeting:
            day = meeting.local_date
            start = meeting.start_at.astimezone(_TZ) if meeting.start_at else None
            end = meeting.end_at.astimezone(_TZ) if meeting.end_at else None
            if start and end and start.date() == end.date():
                day = start.date()
                meeting_args.update(meeting_start=start.time(), meeting_end=end.time())
                keep.remove(meeting)
            elif day:
                keep.remove(meeting)
            meeting_args.update(meeting_requested=True, meeting_date=day,
                                meeting_place=meeting.place[:100] if meeting.place and len(meeting.place) >= 2 else None)
        return TripRequest(trip_id=trip_id, budget=budget,
                           origin=snapshot.origin[:24] if snapshot.origin else None,
                           destination=snapshot.destination[:24] if snapshot.destination else None,
                           depart_date=snapshot.start_date, return_date=snapshot.end_date, **meeting_args), revision, keep
