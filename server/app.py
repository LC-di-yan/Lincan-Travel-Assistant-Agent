"""FastAPI 应用主入口"""
import os
import sys

# Windows 控制台 UTF-8 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        os.system("chcp 65001 >nul 2>&1")

import logging
from contextlib import asynccontextmanager
from pathlib import Path

# 配置日志级别 - 设置根logger确保所有模块的INFO日志都输出
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
if not root_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    root_logger.addHandler(handler)

# 确保项目根目录在 sys.path 中
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动：初始化数据库连接池
    from db.connection import get_pool
    pool = await get_pool()
    if pool:
        logger.info("PostgreSQL connection pool initialized")
    else:
        logger.info("ALIGO_DATABASE_URL not set, using JSON file storage")

    # 启动：初始化 Redis 缓存
    from cache.connection import get_redis
    redis_pool = await get_redis()
    if redis_pool:
        logger.info("Redis cache initialized")

    yield

    # 关闭：释放数据库连接池
    from db.connection import close_pool
    await close_pool()
    # 关闭：释放 Redis 连接池
    from cache.connection import close_redis
    await close_redis()
    logger.info("Aligo Web Server shutting down...")


app = FastAPI(
    title="Aligo 智能旅行助手",
    description="多智能体差旅规划系统 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - 从环境变量读取允许的域名，逗号分隔
# 生产环境应设置 CORS_ORIGINS 环境变量（如 http://your-server-ip）
# 也支持 allow_origin_regex 匹配同源请求
cors_origins = os.environ.get("CORS_ORIGINS", "").split(",")
_default_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000",
    "http://localhost:8000", "http://localhost:8001", "http://127.0.0.1:8001",
]
cors_origins = [o.strip() for o in cors_origins if o.strip()] or _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(cors_origins)),
    allow_origin_regex=r"^https?://[\w\.\-]+(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from server.routes import chat, memory, health
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(memory.router)

# 生产模式：挂载前端静态文件
dist_path = Path(__file__).resolve().parent.parent / "web" / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")
