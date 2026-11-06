"""
AgentScope Configuration for Aligo Multi-Agent Travel Planning System
双版本适配（1.0.16 / 2.0.11）：初始化统一走 utils.as_compat.setup。
"""
import agentscope
from config import LLM_CONFIG
from utils.as_compat import setup as _as_setup

_agentscope_initialized = False

def init_agentscope():
    """
    初始化AgentScope（幂等，多次调用只执行一次）

    说明：
    - 2.0.11 已删除 agentscope.init()（project/name Studio 埋点语义一并移除），
      顶层替代品是 setup_logger(level, filepath)；
    - 1.0.16 下仍保留 init(project=, name=, logging_level=) 行为；
    - 函数名与幂等语义保持不变，全项目 18 处引用零改动。
    """
    global _agentscope_initialized
    if _agentscope_initialized:
        return
    _as_setup(logging_level="INFO")
    _agentscope_initialized = True
    print(f"[OK] AgentScope initialized (version: {agentscope.__version__})")


def get_model_config():
    """
    获取模型配置（用于Agent初始化）

    Returns:
        dict: 模型配置字典
    """
    return {
        "model_type": "openai_chat",  # 使用OpenAI兼容接口
        "config_name": "mimo_api",
        "model_name": LLM_CONFIG["model_name"],
        "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"],
        "temperature": LLM_CONFIG.get("temperature", 0.7),
        "max_tokens": LLM_CONFIG.get("max_tokens", 2000),
    }
