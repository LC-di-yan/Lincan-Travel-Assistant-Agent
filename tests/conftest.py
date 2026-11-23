"""
Shared fixtures for pytest
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure project root is in sys.path
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def pytest_addoption(parser):
    parser.addoption("--live-model", action="store_true", help="运行会调用真实模型的演示用例（可能计费）")


@pytest.fixture()
def live_model(request):
    if not request.config.getoption("--live-model"):
        pytest.skip("真实模型演示需要显式传入 --live-model")
    from config import LLM_CONFIG
    if not LLM_CONFIG.get("api_key"):
        pytest.fail("已请求真实模型演示，但未设置 ALIGO_API_KEY")


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
