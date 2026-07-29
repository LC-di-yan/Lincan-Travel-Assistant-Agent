#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
懒加载智能体注册器
基于 .claude/skills 目录结构的插件化加载机制
"""
import os
import sys
import json
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Any, Optional
import logging
from agentscope.agent import AgentBase

logger = logging.getLogger(__name__)

class LazyAgentRegistry:
    """
    懒加载智能体注册器 - 插件化版本

    自动扫描 .claude/skills 下的技能目录，动态加载 script/agent.py
    """

    CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "plugin_config.json"

    def __init__(self, model, cache: Dict, memory_manager=None, db_pool=None, cache_layer=None, user_id: str = "default_user"):
        self.model = model
        self.cache = cache
        self.memory_manager = memory_manager
        self._pool = db_pool
        self._cache_layer = cache_layer
        self._user_id = user_id

        # 技能目录路径 (基于项目根目录)
        self.skills_root = Path(__file__).resolve().parent.parent / ".claude" / "skills"

        # 技能映射表: skill_name -> agent_script_path
        self._skill_map: Dict[str, Path] = {}

        # 插件配置
        self._plugin_config = self._load_config_sync()

        # 发现技能
        self._discover_skills()

        # 旧版兼容映射 (name -> skill_folder_name)
        self._legacy_mapping = {
            "rag_knowledge": "ask-question",
            "memory_query": "memory-query",
            "preference": "preference",
            "information_query": "query-info",
            "itinerary_planning": "plan-trip",
            "event_collection": "event-collection",
            "expense_tracking": "expense-tracker",
            "expense_tracker": "expense-tracker",
            "currency_conversion": "currency-converter",
            "currency_converter": "currency-converter",
            "visa_info": "visa-info",
            "translation": "translation",
            "train_ticket": "train-ticket",
        }

    def _load_config_sync(self) -> Dict[str, Any]:
        """同步加载插件配置（JSON 文件模式）"""
        if self.CONFIG_PATH.exists():
            try:
                with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    async def _load_config_async(self) -> Dict[str, Any]:
        """异步加载插件配置（PG 模式）"""
        if self._pool:
            rows = await self._pool.fetch(
                "SELECT plugin_name, enabled FROM plugin_config WHERE user_id=$1",
                self._user_id,
            )
            return {r["plugin_name"]: {"enabled": r["enabled"]} for r in rows}
        return self._load_config_sync()

    def _save_config_sync(self):
        """同步保存插件配置（JSON 文件模式）"""
        try:
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._plugin_config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save plugin config: {e}")

    async def _save_config_async(self, skill_name: str, enabled: bool):
        """异步保存单个插件配置（PG 模式）"""
        if self._pool:
            await self._pool.execute(
                """
                INSERT INTO plugin_config(user_id, plugin_name, enabled)
                VALUES($1, $2, $3)
                ON CONFLICT(user_id, plugin_name)
                DO UPDATE SET enabled=$3, updated_at=NOW()
                """,
                self._user_id,
                skill_name,
                enabled,
            )

    def is_plugin_enabled(self, skill_name: str) -> bool:
        """检查插件是否启用"""
        config = self._plugin_config.get(skill_name, {})
        return config.get("enabled", True)

    def set_plugin_enabled(self, skill_name: str, enabled: bool):
        """设置插件启用状态（同步版本，JSON 模式）"""
        if skill_name not in self._plugin_config:
            self._plugin_config[skill_name] = {}
        self._plugin_config[skill_name]["enabled"] = enabled
        self._save_config_sync()

    async def set_plugin_enabled_async(self, skill_name: str, enabled: bool):
        """设置插件启用状态（异步版本，PG 模式）"""
        if skill_name not in self._plugin_config:
            self._plugin_config[skill_name] = {}
        self._plugin_config[skill_name]["enabled"] = enabled
        await self._save_config_async(skill_name, enabled)

    def get_all_plugins(self) -> list:
        """获取所有插件信息"""
        plugins = []
        for skill_name, script_path in sorted(self._skill_map.items()):
            plugins.append({
                "name": skill_name,
                "enabled": self.is_plugin_enabled(skill_name),
                "loaded": skill_name in self.cache,
            })
        return plugins

    def _discover_skills(self):
        """扫描 .claude/skills 目录寻找可用的 Agent"""
        if not self.skills_root.exists():
            logger.warning(f"Skills directory {self.skills_root} not found")
            return

        count = 0
        for skill_dir in self.skills_root.iterdir():
            if not skill_dir.is_dir():
                continue

            # 查找 script/agent.py
            agent_script = skill_dir / "script" / "agent.py"
            if agent_script.exists():
                skill_name = skill_dir.name
                self._skill_map[skill_name] = agent_script
                count += 1

    def _resolve_agent_name(self, agent_name: str) -> Optional[str]:
        """解析智能体名称到技能目录名"""
        # 1. 直接匹配技能名
        if agent_name in self._skill_map:
            return agent_name

        # 2. 尝试遗留映射
        if agent_name in self._legacy_mapping:
            skill_name = self._legacy_mapping[agent_name]
            if skill_name in self._skill_map:
                return skill_name

        # 3. 模糊匹配：将 PascalCase/camelCase 转为 snake_case 后重试
        import re
        snake = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', agent_name).lower()
        snake_clean = re.sub(r'_agent$', '', snake)
        if snake_clean in self._legacy_mapping:
            skill_name = self._legacy_mapping[snake_clean]
            if skill_name in self._skill_map:
                return skill_name
        if snake_clean in self._skill_map:
            return snake_clean

        # 4. 遍历 _skill_map 做包含匹配
        for skill_name in self._skill_map:
            if skill_name.replace('-', '_') == snake_clean:
                return skill_name

        return None

    def __getitem__(self, agent_name: str):
        """获取智能体 (懒加载)"""
        if agent_name in self.cache:
            return self.cache[agent_name]

        skill_name = self._resolve_agent_name(agent_name)

        # 检查插件是否启用
        if skill_name and not self.is_plugin_enabled(skill_name):
            raise KeyError(f"Agent '{agent_name}' is disabled")
        if not skill_name:
             raise KeyError(f"Agent '{agent_name}' not found in skills directory")

        script_path = self._skill_map[skill_name]

        logger.info(f"Loading {agent_name} (from {skill_name})...")

        try:
            # 1. 动态加载模块
            module_name = f"skills.{skill_name}.agent"
            spec = importlib.util.spec_from_file_location(module_name, script_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load spec from {script_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            # 关键：确保模块能找到项目根目录的包
            project_root = str(Path(__file__).parent.parent.absolute())
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            spec.loader.exec_module(module)

            # 2. 查找 Agent 类
            agent_class = None
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, AgentBase) and obj is not AgentBase:
                    agent_class = obj
                    break

            if not agent_class:
                raise ValueError(f"No AgentBase subclass found in {script_path}")

            # 3. 实例化
            init_params = {
                "name": agent_name,
                "model": self.model,
            }

            sig = inspect.signature(agent_class.__init__)
            if "memory_manager" in sig.parameters:
                init_params["memory_manager"] = self.memory_manager

            agent_instance = agent_class(**init_params)

            # 注入缓存层
            if self._cache_layer is not None:
                agent_instance._cache_layer = self._cache_layer

            # 4. 缓存
            self.cache[agent_name] = agent_instance
            logger.info(f"[OK] {agent_name} loaded")

            return agent_instance

        except Exception as e:
            logger.error(f"[FAIL] Loading {agent_name} failed: {e}")
            import traceback
            traceback.print_exc()
            raise

    def __contains__(self, agent_name: str) -> bool:
        return self._resolve_agent_name(agent_name) is not None or agent_name in self.cache

    def get(self, agent_name: str, default=None):
        try:
            return self[agent_name]
        except KeyError:
            return default

    def keys(self):
        keys = set(self._skill_map.keys())
        for legacy_key, skill_val in self._legacy_mapping.items():
            if skill_val in self._skill_map:
                keys.add(legacy_key)
        return list(keys)

    def values(self):
        return self.cache.values()

    def items(self):
        return self.cache.items()

    def get_loaded_agents(self) -> list:
        return list(self.cache.keys())
