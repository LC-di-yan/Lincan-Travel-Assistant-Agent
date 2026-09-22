"""
Shared fixtures for pytest
"""
import os
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from dotenv import load_dotenv

# Ensure project root is in sys.path
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 与 config.py 相同的凭证解析方式（先读 .env，再读环境变量）
load_dotenv()

_LLM_CONFIGURED = bool(os.environ.get("ALIGO_API_KEY"))


def pytest_collection_modifyitems(config, items):
    """未配置 ALIGO_API_KEY 时跳过标了 integration 的测试。

    这些测试会真实调用 LLM API，缺少凭证时必然抛 openai.OpenAIError，
    使 `pytest` 在干净克隆上直接变红。改成跳过可以保留它们的价值
    （配置好 .env 后自动参与），同时不干扰本地和 CI 的常规回归。
    """
    if _LLM_CONFIGURED:
        return
    skip_integration = pytest.mark.skip(
        reason="未配置 ALIGO_API_KEY，跳过需要真实 LLM 的集成测试（配置 .env 后自动启用）"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def mock_model():
    """Mock LLM model that returns a configurable response"""
    model = AsyncMock()
    model.return_value = MagicMock()
    model.return_value.text = '{"answer": "mock response"}'
    return model


@pytest.fixture
def mock_memory():
    """Mock memory manager"""
    memory = MagicMock()
    memory.long_term = MagicMock()
    memory.long_term.get_expenses.return_value = []
    memory.long_term.get_preference.return_value = {}
    memory.long_term.get_chat_history.return_value = []
    memory.long_term.get_trip_history.return_value = []
    memory.long_term.get_frequent_destinations.return_value = []
    memory.long_term.get_statistics.return_value = {
        "total_trips": 0,
        "total_messages": 0,
        "total_queries": 0,
        "frequent_destinations": {}
    }
    return memory


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for tests"""
    return tmp_path
