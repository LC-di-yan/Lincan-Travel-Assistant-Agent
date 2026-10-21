"""
Configuration for the Aligo Multi-Agent System
"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM Configuration (优先从环境变量读取)
LLM_CONFIG = {
    "api_key": os.environ.get("ALIGO_API_KEY", ""),
    "model_name": os.environ.get("ALIGO_MODEL_NAME", "glm-5.2-fast-preview"),
    "base_url": os.environ.get("ALIGO_BASE_URL", "https://ws-qvg9u4gn3ewyjs3t.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"),
    "temperature": 0.7,
    "max_tokens": 2048,  # 默认值，各场景通过 SCENARIO_TOKENS 覆盖
}


def _env_list(name: str):
    """取逗号分隔的环境变量，去掉空项。"""
    raw = os.environ.get(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


# 备用模型通道（主通道 401/403/429/5xx 时自动切换，见 utils/llm_failover.py）
# 三个变量按位置一一对应：BASE_URLS / MODEL_NAMES / API_KEYS（API_KEYS 可少写，
# 缺省时沿用 ALIGO_API_KEY）。
LLM_FALLBACKS = []
_fb_bases = _env_list("ALIGO_FALLBACK_BASE_URLS")
_fb_models = _env_list("ALIGO_FALLBACK_MODEL_NAMES")
_fb_keys = _env_list("ALIGO_FALLBACK_API_KEYS")
for _i, (_b, _m) in enumerate(zip(_fb_bases, _fb_models), start=1):
    LLM_FALLBACKS.append({
        "name": f"fallback{_i}",
        "base_url": _b,
        "model_name": _m,
        "api_key": _fb_keys[_i - 1] if len(_fb_keys) >= _i else LLM_CONFIG["api_key"],
    })

# 启动时探活一次（消耗极少 token），日志里直接看出哪条通道可用
LLM_PROBE_ON_STARTUP = os.environ.get("ALIGO_LLM_PROBE_ON_STARTUP", "1").strip() not in ("0", "false", "False")

# 按场景 token 预算 — 减少 LLM 输出 token 数以提速
SCENARIO_TOKENS = {
    "intention": 4096,           # 意图识别（长 prompt + MiMo 思考 1000-1500 token，需足够余量）
    "event_collection": 4096,    # 事项提取（同上）
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

# TTS Configuration（小米 MiMo，独立于 LLM 的阿里云 MAAS）
# 实测确认：MiMo 用 api-key 头认证（非 Authorization），返回裸 PCM16（24kHz 单声道）
TTS_CONFIG = {
    "api_key": os.environ.get("MIMO_API_KEY", ""),
    "base_url": os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
    "model": os.environ.get("MIMO_TTS_MODEL", "mimo-v2.5-tts"),
    "default_voice": os.environ.get("MIMO_TTS_VOICE", "冰糖"),
    "default_style": "用自然亲切的语气朗读",
    "sample_rate": 24000,
    "timeout_sec": 60.0,
    "connect_timeout_sec": 5.0,
}

# Narration Configuration（语音播报文案生成，独立于主对话 LLM）
# 用 GLM-5.2（思考模型，流式输出 reasoning + content，仅透传 content）
NARRATION_CONFIG = {
    "api_key": os.environ.get("NARRATION_API_KEY", ""),
    "base_url": os.environ.get("NARRATION_BASE_URL", "https://tokenrhythm.studio/v1"),
    "model": os.environ.get("NARRATION_MODEL", "glm-5.2"),
    "max_tokens": 1500,  # 思考阶段 600-1000 tokens，正式文案 50-150 tokens
    "temperature": 0.7,
    "timeout_sec": 30.0,
    "connect_timeout_sec": 5.0,
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
