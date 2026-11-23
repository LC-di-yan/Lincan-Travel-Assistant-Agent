"""Exposed dependency graph for complete trip requests; not a third Agent."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from weakref import WeakKeyDictionary

from agents.trip_decision import MAX_TOOL_CANDIDATES, evaluate_trip
from utils.as_compat import mk_msg, msg_json
from utils.provider_http import amap_json
from utils.trip_request import TripRequest, TripTurn
from utils.weather_range import shanghai_now

logger = logging.getLogger(__name__)
MAX_RUNNING = 4
GLOBAL_READ_LIMIT = 16
TOTAL_TIMEOUT = 30.0
_limits = WeakKeyDictionary()
_walking_limits = WeakKeyDictionary()


@dataclass(frozen=True)
class Node:
    node_id: str
    agent_name: str
    label: str
    depends_on: tuple[str, ...] = ()
    timeout: float = 12.0

    def public(self):
        return {"node_id": self.node_id, "agent_name": self.agent_name, "label": self.label,
                "depends_on": list(self.depends_on), "priority": 2 if self.depends_on else 1}


def build_graph(req: TripRequest) -> tuple[Node, ...]:
    nodes = [Node("outbound", "train_ticket", "查询去程交通", timeout=17)]
    if not req.one_way:
        nodes.append(Node("inbound", "train_ticket", "查询返程交通", timeout=17))
    if req.nights:
        nodes.append(Node("hotels", "hotel_search", "查询住宿候选"))
    nodes.append(Node("weather", "information_query", "查询目的地天气"))
    if req.nights and req.meeting_place:
        nodes.append(Node("commute", "trip_commute", "核验酒店至会场通勤", ("hotels",)))
    nodes.append(Node("proposal", "itinerary_planning", "验证预算和时间并比较方案",
                      tuple(node.node_id for node in nodes if node.node_id != "weather")))
    return tuple(nodes)


def trip_intention(turn: TripTurn) -> dict:
    req = turn.request
    entities = {key: value for key in ("origin", "destination") if (value := getattr(req, key))}
    if req.depart_date:
        entities["start_date"] = req.depart_date.isoformat()
    if req.effective_return:
        entities["end_date"] = req.effective_return.isoformat()
    return {
        "intents": [{"type": "itinerary_planning", "confidence": 1, "description": "完整差旅规划", "reason": ""}],
        "key_entities": entities,
        "trip_request": req.public(),
        "agent_schedule": [] if turn.missing else [node.public() for node in build_graph(req)],
        "needs_clarification": bool(turn.missing),
        "clarification_question": turn.question if turn.missing else "",
        "missing_fields": [{"field": key, "label": label} for key, label in turn.missing],
    }


def _tool_input(node: Node, req: TripRequest) -> tuple[tuple, dict]:
    if node.node_id in {"outbound", "inbound"}:
        incoming = node.node_id == "inbound"
        origin, dest = (req.destination, req.origin) if incoming else (req.origin, req.destination)
        day = (req.effective_return if incoming else req.depart_date).isoformat()
        period = req.return_period if incoming else req.depart_period
        train_types = ["G", "D", "C"] if req.transport_required == "high_speed" else []
        key = ("rail", origin, dest, day, period, tuple(train_types), req.transport_required)
        data = {"context": {"rewritten_query": f"{day}从{origin}到{dest}的火车票"},
                "fast_train_ticket": {"from": origin, "to": dest, "date": day,
                                      "period": period or "", "train_types": train_types}}
        return key, data
    if node.node_id == "hotels":
        location = req.meeting_place if req.near_meeting else None
        # POI is not a room quote. Keep trip budget out of map keyword extraction.
        label = f"{location}附近酒店" if location else "酒店"
        return ("hotel", req.destination, location), {
            "context": {"agent_name": node.agent_name, "key_entities": {"destination": req.destination},
                        "rewritten_query": f"{req.destination}{label}"},
        }
    start = req.depart_date.isoformat()
    end = (req.effective_return or req.depart_date).isoformat()
    return ("weather", req.destination, start, end), {
        "context": {"rewritten_query": f"{req.destination}{start}{'到' + end if end != start else ''}天气",
                    "key_entities": {"destination": req.destination}},
    }


def _coordinates(value) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"-?\d{1,3}(?:\.\d{1,8})?,-?\d{1,2}(?:\.\d{1,8})?", value):
        return None
    lon, lat = map(float, value.split(","))
    return value if -180 <= lon <= 180 and -90 <= lat <= 90 else None


async def query_commute(request: TripRequest, hotels: list[dict]) -> dict:
    from config import AMAP_CONFIG

    key = AMAP_CONFIG.get("api_key")
    candidates = [(h.get("id"), _coordinates(h.get("location"))) for h in hotels if isinstance(h, dict)]
    candidates = [(str(hid)[:100], loc) for hid, loc in candidates if isinstance(hid, str) and hid and loc]
    if not key or not request.meeting_place or not candidates:
        return {}
    base = AMAP_CONFIG.get("base_url", "https://restapi.amap.com/v3")
    geocode = await amap_json(f"{base}/geocode/geo", {"key": key, "city": request.destination, "address": request.meeting_place})
    matches = geocode.get("geocodes")
    if geocode.get("status") != "1" or not isinstance(matches, list) or len(matches) != 1:
        return {}
    point = matches[0]
    if not isinstance(point, dict):
        return {}
    actual_city = point.get("city") or point.get("province") or ""
    if not isinstance(actual_city, str) or actual_city.removesuffix("市") != request.destination:
        return {}
    if not point.get("level") or point["level"] in {"省", "市", "区县", "开发区", "乡镇", "区县级", "城市"}:
        return {}
    destination = _coordinates(point.get("location"))
    if not destination:
        return {}

    limit = _walking_limits.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(8))

    async def walk(origin):
        try:
            async with limit:
                response = await amap_json(f"{base}/direction/walking", {"key": key, "origin": origin, "destination": destination})
            if response.get("status") != "1":
                return None
            path = response["route"]["paths"][0]
            meters, seconds = int(path["distance"]), int(path["duration"])
            if 0 <= meters <= 100_000 and 0 <= seconds <= 86400:
                return {"distance_m": meters, "duration_min": (seconds + 59) // 60, "quality": "reference_estimate",
                        "source_url": "https://www.amap.com/", "queried_at": shanghai_now().isoformat()}
        except (ValueError, TypeError, LookupError):
            return None
        return None

    # Multiple POIs may share a door: one request per unique starting point.
    origins = list(dict.fromkeys(loc for _, loc in candidates))[:MAX_TOOL_CANDIDATES]
    routes = dict(zip(origins, await asyncio.gather(*(walk(loc) for loc in origins)), strict=True))
    return {hid: routes[loc] for hid, loc in candidates if routes.get(loc)}


def _data_status(data: dict, node_id: str) -> str:
    if data.get("query_success") is not True:
        return "unavailable" if data.get("availability_status") == "unavailable" else "failed"
    if data.get("availability_status") == "partial":
        return "partial"
    field = {"outbound": "trains", "inbound": "trains", "hotels": "hotels", "weather": "forecast"}.get(node_id)
    if field and (not isinstance(data.get("results"), dict) or not data["results"].get(field)):
        return "unavailable"
    return "success"


def _unavailable(message: str) -> dict:
    return {"query_success": False, "availability_status": "unavailable", "results": {"message": message}}


def _route_candidates(data: dict) -> list[dict]:
    body = data.get("results")
    hotels = body.get("hotels") if isinstance(body, dict) else None
    return [item for item in hotels[:MAX_TOOL_CANDIDATES] if isinstance(item, dict)] if isinstance(hotels, list) else []


async def run_trip_workflow(req: TripRequest, registry, queue, cache: dict, *, ranking_hints=None) -> dict:
    graph = build_graph(req)
    waiting = {node.node_id: node for node in graph}
    running: dict[asyncio.Task, Node] = {}
    finished: dict[str, dict] = {}
    evidence: dict[str, dict] = {}
    deadline = asyncio.get_running_loop().time() + TOTAL_TIMEOUT
    limit = _limits.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(GLOBAL_READ_LIMIT))

    def publish(event, payload):
        if queue is not None:
            queue.put_nowait({**payload, "type": event})

    def frame(node, status, data, reused=False):
        return {**node.public(), "status": "success" if status in {"success", "partial"} else "error",
                "node_status": status, "cached": reused, "data": data}

    def plan_data():
        plan = evaluate_trip(req, evidence, shanghai_now(), ranking_hints=ranking_hints)
        headline = ("已验证交通与住宿等可判定约束；请查看附带的数据缺项。" if plan["recommended"] and plan["status"] == "partial" else
                    "已验证的推荐方案与备选" if plan["recommended"] else
                    "没有能够确认满足全部约束的方案；以下仅为可核验的部分结果或失败说明。")
        return {"trip_plan": plan, "answer": headline}

    async def execute(node: Node):
        async with asyncio.timeout_at(min(deadline, asyncio.get_running_loop().time() + node.timeout)):
            if node.node_id == "proposal":
                data = plan_data()
                return data, "success" if data["trip_plan"]["status"] == "success" else "partial", False
            if node.node_id == "commute":
                hotels = _route_candidates(evidence.get("hotels", {}))
                if not hotels:
                    return _unavailable("住宿查询未得到候选，无法核验通勤。"), "skipped", False
                key = ("commute", req.destination, req.meeting_place, tuple((h.get("id"), h.get("location")) for h in hotels))
            else:
                if node.node_id in {"outbound", "inbound"} and req.transport_required == "flight":
                    return _unavailable("缺少获授权的航班证据接口，未以铁路代替。"), "unavailable", False
                key, data = _tool_input(node, req)
            key = (req.trip_id, key)
            if entry := cache.get(key):
                until, old = entry
                if until > time.monotonic():
                    return old, "success", True
                cache.pop(key)
            async with limit:
                if node.node_id == "commute":
                    routes = await query_commute(req, hotels)
                    data = {"routes": routes, "answer": "通勤为地图步行估算，不是实时路况。" if routes else "未核验酒店至会场路线。"}
                    status = ("success" if len(routes) == len(hotels) else "partial") if routes else "unavailable"
                else:
                    agent = registry.get(node.agent_name)
                    if agent is None:
                        return _unavailable("该能力未启用或当前不可用。"), "unavailable", False
                    response = msg_json(await agent.reply(mk_msg("Orchestrator", data, role="user")), default={})
                    data = response if isinstance(response, dict) else {}
                    status = _data_status(data, node.node_id)
                    if status == "unavailable" and not data.get("results"):
                        data = _unavailable("未取得可核验的数据。")
                    if status in {"success", "partial"} and isinstance(data.get("results"), dict):
                        data["results"].setdefault("received_at", shanghai_now().isoformat())
            if status == "success":
                ttl = {"outbound": 60, "inbound": 60, "hotels": 180, "weather": 300, "commute": 180}[node.node_id]
                cache[key] = (time.monotonic() + ttl, data)
                while len(cache) > 48:
                    cache.pop(next(iter(cache)))
            return data, status, False

    def accept(node, data, status, reused=False):
        frame_data = frame(node, status, data, reused)
        evidence[node.node_id] = data
        finished[node.node_id] = frame_data
        publish("agent_result", frame_data)

    try:
        while waiting or running:
            for node in tuple(waiting.values()):
                if len(running) >= MAX_RUNNING:
                    break
                if all(dep in finished for dep in node.depends_on):
                    waiting.pop(node.node_id)
                    publish("agent_start", {**node.public(), "status": "running", "node_status": "running"})
                    running[asyncio.create_task(execute(node), name=f"trip:{node.node_id}")] = node
            if not running:
                break
            done, _ = await asyncio.wait(tuple(running), timeout=max(0, deadline - asyncio.get_running_loop().time()),
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for task in sorted(done, key=lambda item: graph.index(running[item])):
                node = running.pop(task)
                try:
                    data, status, reused = task.result()
                except TimeoutError:
                    data, status, reused = _unavailable("该步骤查询超时。"), "timeout", False
                except Exception as exc:
                    logger.warning("Trip node %s failed (%s)", node.node_id, type(exc).__name__)
                    data, status, reused = _unavailable("该步骤暂时不可用。"), "failed", False
                accept(node, data, status, reused)
    finally:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
    for node in [*running.values(), *waiting.values()]:
        if node.node_id != "proposal":
            accept(node, _unavailable("任务达到总时限，本步骤未取得结果。"), "timeout")

    final_data = plan_data()
    proposal = graph[-1]
    final_status = "success" if final_data["trip_plan"]["status"] == "success" else "partial"
    if "proposal" not in finished:
        accept(proposal, final_data, final_status)
    else:
        # Optional weather need not delay the early assessment. The final snapshot carries its outcome.
        finished["proposal"] = frame(proposal, final_status, final_data)
    results = [finished[node.node_id] for node in graph if node.node_id in finished]
    issues = [row for row in results if row["node_status"] != "success"]
    reads = [row for row in results if row["node_id"] in {"outbound", "inbound", "hotels", "weather"}]
    has_evidence = any(row["node_status"] in {"success", "partial"} for row in reads)
    final = "completed" if not issues else "partial_failure" if has_evidence else "failed"
    return {"status": final, "trip_plan": final_data["trip_plan"], "results": results,
            "agents_executed": sum(row["node_id"] != "commute" and not row["cached"] for row in results),
            "errors": len(issues)}
