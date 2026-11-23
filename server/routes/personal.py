"""本人个人中心接口。聊天、历史与旧账本路由不变。"""
import base64
import binascii
from datetime import date, datetime
import json
import logging
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from server.auth import CurrentUser
from server.personal.access import check_personal_write, csrf_for, personal_enabled, secure_personal_site
from server.personal.candidates import candidates
from server.personal.finance import LedgerProfile
from server.personal.models import (AssignmentCommit, AssignmentPreview, CreateTrip, FavoriteInput, NewVersion, OperationCommit,
                                    OperationPreview, PreferenceEdit, PreferenceKey, PreferenceSettings, RenameTrip)
from server.personal.profile import Favorites, Profile
from server.personal.repository import trip_repository
from server.personal.service import PersonalError, Trips

logger = logging.getLogger(__name__)


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        standard = super().get_route_handler()

        async def handle(request):
            try:
                return await standard(request)
            except PersonalError as exc:
                return _failure(exc.status, exc.code, exc.message, details=exc.details)
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42P01" and not isinstance(exc, OSError):
                    raise
                correlation_id = uuid4().hex
                logger.warning("Personal data unavailable (%s), correlation_id=%s", type(exc).__name__, correlation_id)
                return _failure(503, "personal_storage_unavailable", "个人行程资料暂不可用，请稍后重试。",
                                correlation_id=correlation_id)
        return handle


def _failure(status, code, message, *, details=None, correlation_id=None):
    return JSONResponse(status_code=status, content={
        "code": code, "message": message, "details": details, "correlation_id": correlation_id or uuid4().hex,
    })


router = APIRouter(prefix="/api/personal", route_class=PrivateRoute)


@router.get("/capabilities")
async def capabilities(request: Request, current_user: CurrentUser):
    available = personal_enabled() and secure_personal_site(request)
    return {"enabled": available, "csrf_token": csrf_for(current_user) if available else None}


def require_personal(request):
    if not personal_enabled():
        raise PersonalError(404, "feature_unavailable", "个人中心尚未开放。")
    if not secure_personal_site(request):
        raise PersonalError(403, "secure_site_required", "个人中心需要 HTTPS。")


async def personal_store(request: Request, current_user: CurrentUser):
    require_personal(request)
    return Trips(await trip_repository(current_user))


async def personal_writer(request: Request, current_user: CurrentUser):
    require_personal(request)
    check_personal_write(request, current_user)
    return Trips(await trip_repository(current_user))


Reader = Annotated[Trips, Depends(personal_store)]
Writer = Annotated[Trips, Depends(personal_writer)]
Key = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[a-zA-Z0-9_-]{16,96}$")]
Match = Annotated[str, Header(alias="If-Match", pattern=r'^"[1-9][0-9]{0,8}"$')]
Lifecycle = Literal["draft", "scheduled", "completed", "cancelled", "superseded", "archived"]


def _decode_cursor(value):
    if value is None:
        return None
    try:
        cursor = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        stamp, identity = cursor
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp).utcoffset() is None:
            raise ValueError()
        return stamp, str(UUID(identity))
    except (binascii.Error, ValueError, TypeError, AttributeError):
        raise PersonalError(422, "invalid_cursor", "列表位置无效，请返回第一页。") from None


def _encode_cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode() if value else None


@router.get("/overview")
async def overview(trips: Reader):
    return await trips.overview()


@router.get("/legacy-trips")
async def legacy(trips: Reader):
    return await trips.legacy()


@router.get("/candidates/{candidate_ref}/conflicts")
async def candidate_conflicts(candidate_ref: UUID, current_user: CurrentUser, trips: Reader,
                              session_id: Annotated[str, Query(pattern=r"^[\w-]{1,32}$")]):
    snapshot = candidates.get(current_user, session_id, candidate_ref)
    if snapshot is None:
        raise PersonalError(404, "candidate_unavailable", "找不到这一轮的规划结果，请重新生成。")
    return await trips.candidate_conflicts(snapshot)


@router.get("/trips")
async def list_trips(trips: Reader, status: Lifecycle | None = None, search: Annotated[str | None, Query(max_length=100)] = None,
                     cursor: Annotated[str | None, Query(max_length=160)] = None, limit: Annotated[int, Query(ge=1, le=60)] = 30,
                     start_date: date | None = None, end_date: date | None = None):
    if start_date and end_date and start_date > end_date:
        raise PersonalError(422, "invalid_date_range", "起始日期不能晚于结束日期。")
    result = await trips.list(status=status, search=search, cursor=_decode_cursor(cursor), limit=limit,
                              start_date=start_date, end_date=end_date)
    result["next_cursor"] = _encode_cursor(result["next_cursor"])
    return result


@router.post("/trips", status_code=201)
async def create_trip(payload: CreateTrip, trips: Writer, key: Key):
    return await trips.create(payload, key)


@router.get("/trips/{plan_id}")
async def get_trip(plan_id: UUID, response: Response, trips: Reader):
    result = await trips.get(plan_id)
    response.headers["ETag"] = f'"{result["plan"]["revision"]}"'
    return result


@router.patch("/trips/{plan_id}")
async def rename_trip(plan_id: UUID, payload: RenameTrip, trips: Writer, match: Match):
    return await trips.rename(plan_id, payload.title, int(match[1:-1]))


@router.get("/trips/{plan_id}/versions")
async def list_versions(plan_id: UUID, trips: Reader):
    return await trips.versions(plan_id)


@router.get("/trips/{plan_id}/versions/{version}")
async def get_version(plan_id: UUID, version: int, trips: Reader):
    return await trips.version(plan_id, version)


@router.post("/trips/{plan_id}/versions", status_code=201)
async def add_version(plan_id: UUID, payload: NewVersion, trips: Writer, match: Match, key: Key):
    return await trips.add_version(plan_id, payload, int(match[1:-1]), key)


@router.post("/trips/{plan_id}/operations/preview")
async def preview_operation(plan_id: UUID, payload: OperationPreview, trips: Writer):
    return await trips.preview(plan_id, payload)


@router.post("/trips/{plan_id}/operations/commit")
async def commit_operation(plan_id: UUID, payload: OperationCommit, trips: Writer, key: Key):
    return await trips.commit(plan_id, payload, key)


@router.get("/expenses/summary")
async def expense_report(trips: Reader, plan_id: UUID | None = None, unassigned: bool = False, start_date: date | None = None,
                         end_date: date | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                         offset: Annotated[int, Query(ge=0, le=100000)] = 0):
    if plan_id and unassigned:
        raise PersonalError(422, "invalid_expense_scope", "请在指定行程和未归属费用之间选择一种范围。")
    if start_date and end_date and start_date > end_date:
        raise PersonalError(422, "invalid_date_range", "起始日期不能晚于结束日期。")
    return await LedgerProfile(trips.repository).report(plan_id=plan_id, unassigned=unassigned,
                                                        start_date=start_date, end_date=end_date, offset=offset, limit=limit)


@router.post("/expenses/{entry_ref}/assignment/preview")
async def preview_assignment(entry_ref: UUID, payload: AssignmentPreview, trips: Writer):
    return await LedgerProfile(trips.repository).preview(entry_ref, payload)


@router.post("/expenses/{entry_ref}/assignment/commit")
async def commit_assignment(entry_ref: UUID, payload: AssignmentCommit, trips: Writer, key: Key):
    return await LedgerProfile(trips.repository).assign(entry_ref, payload, key)


@router.get("/preferences")
async def preferences(trips: Reader):
    return await Profile(trips.repository).preferences()


@router.put("/preferences/settings")
async def preference_settings(payload: PreferenceSettings, trips: Writer):
    return await Profile(trips.repository).settings(payload)


@router.put("/preferences/{field}")
async def preference_edit(field: PreferenceKey, payload: PreferenceEdit, trips: Writer):
    return await Profile(trips.repository).edit(field, payload)


@router.get("/favorites")
async def favorites(trips: Reader, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                    offset: Annotated[int, Query(ge=0, le=500)] = 0):
    return await Favorites(trips.repository).list(limit=limit, offset=offset)


@router.post("/favorites", status_code=201)
async def create_favorite(payload: FavoriteInput, trips: Writer):
    return await Favorites(trips.repository).create(payload)


@router.delete("/favorites/{favorite_id}")
async def remove_favorite(favorite_id: UUID, trips: Writer):
    return await Favorites(trips.repository).delete(favorite_id)
