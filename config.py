"""
Configuration for the Aligo Multi-Agent System
"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM Configuration (优先从环境变量读取)
LLM_CONFIG = {
    "api_key": os.environ.get("ALIGO_API_KEY", ""),
    "model_name": os.environ.get("ALIGO_MODEL_NAME", "mimo-v2-pro"),
    "base_url": os.environ.get("ALIGO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
    "temperature": 0.7,
    "max_tokens": 2048,  # 默认值，各场景通过 SCENARIO_TOKENS 覆盖
}

# 按场景 token 预算 — 减少 LLM 输出 token 数以提速
SCENARIO_TOKENS = {
    "intention": 1024,           # 意图识别：只需输出 ~200 字 JSON
    "event_collection": 1024,    # 事项提取：只需输出 ~300 字 JSON
    "itinerary": 2048,           # 简单行程（≤1 天）
    "itinerary_complex": 4096,   # 复杂行程（多日 / 多城市）
    "rag": 2048,                 # 知识库问答
    "info_query": 2048,          # 天气 / 搜索
    "chat": 1024,                # 闲聊 / 记忆总结
}

# System Configuration
SYSTEM_CONFIG = {
    "enable_llm": True,
    "log_level": "INFO",
    "max_retries": 2,
    "timeout": 60,
}

# RAG 知识库：嵌入模型
# 首次运行时会自动从 HuggingFace 下载 BAAI/bge-small-zh-v1.5 (~90MB)
# 如需使用本地模型，将路径改为本地目录即可
RAG_CONFIG = {
    "embedding_model": os.environ.get("ALIGO_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
}

# PostgreSQL（空字符串 = 回退 JSON 文件模式）
DATABASE_URL = os.environ.get("ALIGO_DATABASE_URL", "")

# Redis 缓存（空字符串 = 回退进程内 dict）
REDIS_URL = os.environ.get("ALIGO_REDIS_URL", "")
CACHE_DEFAULT_TTL = int(os.environ.get("ALIGO_CACHE_TTL", "3600"))

# 高德天气 Amap
AMAP_CONFIG = {
    "api_key": os.environ.get("AMAP_API_KEY", ""),
    "base_url": "https://restapi.amap.com/v3",
}

# 连接与可用性：重试、熔断、健康检查
RESILIENCE_CONFIG = {
    "max_retries": 2,
    "retry_base_delay_sec": 0.5,
    "retry_max_delay_sec": 8.0,
    "circuit_failure_threshold": 5,
    "circuit_recovery_timeout_sec": 60.0,
    "circuit_half_open_successes": 2,
    "health_check_timeout_sec": 10.0,
}
