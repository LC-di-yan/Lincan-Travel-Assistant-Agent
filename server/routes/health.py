"""健康检查端点"""
import time
from fastapi import APIRouter

router = APIRouter(tags=["health"])

_start_time = time.time()


@router.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "uptime_sec": round(time.time() - _start_time, 1),
    }
