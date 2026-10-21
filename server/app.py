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
    _fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    # 控制台 handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_fmt)
    root_logger.addHandler(stream_handler)
    # 文件 handler（Windows + uvicorn 子进程下 stdout 可能被吞，文件作为可观测性兜底）
    try:
        _log_dir = Path(__file__).resolve().parent.parent / "logs"
        _log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(_log_dir / "server.log", encoding="utf-8")
        file_handler.setFormatter(_fmt)
        root_logger.addHandler(file_handler)
    except Exception as _e:
        # 日志文件初始化失败不应阻断启动
        root_logger.warning(f"FileHandler init failed: {_e}")

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

    # 启动：预加载 RAG Embedding 模型（避免首次请求时加载导致进程崩溃）
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5", local_files_only=True)
        _dim = _model.get_sentence_embedding_dimension()
        logger.info(f"RAG embedding model pre-loaded (dim={_dim})")
    except Exception as _e:
        logger.warning(f"RAG embedding model pre-load failed: {_e}")

    # 启动：模型通道探活
    # 2026-10-20 事故：主通道被上游回收（403 AccessDenied.Unpurchased），
    # 因为没有启动自检，直到用户提问才暴露。这里开机就打一行结论。
    try:
        from config import LLM_CONFIG, LLM_FALLBACKS, LLM_PROBE_ON_STARTUP
        from utils.llm_failover import build_chat_model

        _llm = build_chat_model(LLM_CONFIG, LLM_FALLBACKS, timeout=15.0)
        if LLM_PROBE_ON_STARTUP and hasattr(_llm, "probe"):
            _report = await _llm.probe()
            for _ch in _report.get("channels", []):
                if _ch.get("ok"):
                    logger.info("[LLM] 通道可用：%s (%s)", _ch.get("name"), _ch.get("model"))
                else:
                    logger.warning(
                        "[LLM] 通道不可用：%s (%s) -> %s",
                        _ch.get("name"), _ch.get("model"), _ch.get("error"),
                    )
            if not _report.get("active"):
                logger.error("[LLM] 所有通道均不可用，行程规划等需要模型的步骤会失败")
    except Exception as _e:
        logger.warning(f"LLM channel probe skipped: {_e}")

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
from server.routes import chat, memory, health, tts, narrate
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(tts.router)
app.include_router(narrate.router)

@app.middleware("http")
async def no_cache_index(request, call_next):
    """index.html 不缓存。

    重新构建后 index.html 会引用新的 asset hash；如果浏览器缓存了旧
    index，会去加载已经不存在的旧 JS，表现为整页黑屏/空白。
    """
    response = await call_next(request)
    if request.url.path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


# 生产模式：挂载前端静态文件
dist_path = Path(__file__).resolve().parent.parent / "web" / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.app:app",
        host=os.environ.get("ALIGO_HOST", "0.0.0.0"),
        port=int(os.environ.get("ALIGO_PORT", "3003")),
    )
