"""Tests for plugin configuration in LazyAgentRegistry"""
import pytest
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root in path
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class TestPluginConfig:
    """Test plugin enable/disable functionality"""

    def test_default_plugin_enabled(self, tmp_path):
        """Plugins should be enabled by default"""
        config_path = tmp_path / "plugin_config.json"
        with patch.object(type(config_path), 'exists', return_value=False):
            from agents.lazy_agent_registry import LazyAgentRegistry
            registry = LazyAgentRegistry.__new__(LazyAgentRegistry)
            registry._plugin_config = {}
            assert registry.is_plugin_enabled("any-plugin") is True

    def test_plugin_disabled_via_config(self, tmp_path):
        """Disabled plugin should return False"""
        from agents.lazy_agent_registry import LazyAgentRegistry
        registry = LazyAgentRegistry.__new__(LazyAgentRegistry)
        registry._plugin_config = {"test-plugin": {"enabled": False}}
        assert registry.is_plugin_enabled("test-plugin") is False

    def test_set_plugin_enabled(self, tmp_path):
        """set_plugin_enabled should update config"""
        from agents.lazy_agent_registry import LazyAgentRegistry
        registry = LazyAgentRegistry.__new__(LazyAgentRegistry)
        registry._plugin_config = {}
        registry.CONFIG_PATH = tmp_path / "config.json"

        registry.set_plugin_enabled("my-plugin", False)
        assert registry._plugin_config["my-plugin"]["enabled"] is False

        registry.set_plugin_enabled("my-plugin", True)
        assert registry._plugin_config["my-plugin"]["enabled"] is True

    def test_config_persistence(self, tmp_path):
        """Config should be saved to file"""
        from agents.lazy_agent_registry import LazyAgentRegistry
        registry = LazyAgentRegistry.__new__(LazyAgentRegistry)
        registry._plugin_config = {}
        registry.CONFIG_PATH = tmp_path / "config.json"

        registry.set_plugin_enabled("persist-test", False)

        # Read the file directly
        with open(tmp_path / "config.json", 'r') as f:
            saved = json.load(f)
        assert saved["persist-test"]["enabled"] is False
