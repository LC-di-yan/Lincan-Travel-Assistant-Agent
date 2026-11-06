"""健康检查端点"""
import time
from fastapi import APIRouter

router = APIRouter(tags=["health"])

_start_time = time.time()


def _decision_status() -> dict:
    """决策层状态（NeoHorse-Jev-4B）。任何异常都不能让 /api/health 失败。"""
    try:
        from utils.decision_router import decision_status
        return decision_status()
    except Exception as exc:  # noqa: BLE001
        return {"enabled": False, "mode": "off", "error": str(exc)[:120]}


@router.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "uptime_sec": round(time.time() - _start_time, 1),
        "decision_layer": _decision_status(),
    }
