# Aligo 智能旅行助手 - 优化方案

**基于**: 2026-06-03 测试报告
**文档版本**: v1.0

---

## 1. 优化总览

测试中 43/43 用例全部通过，但暴露了以下核心问题：

| 问题类别 | 优先级 | 影响范围 |
|----------|--------|----------|
| 端到端响应慢（平均 95s） | P0 | 用户体验 |
| RAG 查询慢（平均 23s） | P0 | 用户体验 |
| 行程规划 JSON 解析失败 | P1 | 功能可靠性 |
| Embedding 模型重复加载 | P1 | 资源浪费 |
| gRPC keepalive 警告 | P2 | 日志可读性 |
| AgentScope 参数警告 | P2 | 日志可读性 |

---

## 2. P0 - 性能优化

### 2.1 RAG 查询响应优化（目标: 23s → 8s）

**现状**: RAG 查询平均 23.3s，主要耗时在 Embedding 模型加载（首次 ~2s）和 LLM 生成（~15s）。

**优化方案**:

#### 2.1.1 Embedding 模型单例化

**问题**: 每次创建 `RAGKnowledgeAgent` 都会重新加载 `SentenceTransformer` 模型（~2s）。

**文件**: `.claude/skills/ask-question/script/agent.py`

```python
# 当前：每次实例化都加载模型
self.embedding_model = SentenceTransformer(model_path_or_id)

# 优化：使用模块级单例
_EMBEDDING_MODEL_CACHE = {}

def _get_embedding_model(model_path: str) -> SentenceTransformer:
    if model_path not in _EMBEDDING_MODEL_CACHE:
        _EMBEDDING_MODEL_CACHE[model_path] = SentenceTransformer(model_path)
    return _EMBEDDING_MODEL_CACHE[model_path]
```

**预期收益**: 首次加载后后续查询节省 ~2s。

#### 2.1.2 Milvus Collection 预加载

**问题**: 每次搜索前调用 `load_collection()` 有额外开销，且在初始化时未预加载。

**文件**: `.claude/skills/ask-question/script/agent.py`

```python
# 当前：搜索时才加载
try:
    self.milvus_client.load_collection(self.collection_name)
except Exception:
    pass

# 优化：在 __init__ 中预加载
def __init__(self, ...):
    ...
    if self.milvus_client.has_collection(collection_name):
        self.milvus_client.load_collection(collection_name)
    self.initialized = True
```

**预期收益**: 消除搜索时的加载延迟。

#### 2.1.3 RAG 结果缓存

**问题**: 相同或相似查询重复检索和调用 LLM。

**方案**: 使用 LRU 缓存对查询结果进行缓存。

```python
from functools import lru_cache
import hashlib

_RAG_CACHE = {}
_RAG_CACHE_MAX_SIZE = 100

def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()

async def reply(self, x):
    ...
    cache_k = _cache_key(user_query)
    if cache_k in _RAG_CACHE:
        return _RAG_CACHE[cache_k]
    ...
    _RAG_CACHE[cache_k] = result
    return result
```

**预期收益**: 重复查询响应时间从 23s 降至 <1s。

#### 2.1.4 LLM 调用参数优化

**问题**: `max_tokens=8192` 对于 RAG 回答通常过大，导致生成时间长。

**方案**: RAG 场景下限制 `max_tokens=2048`。

```python
# RAG Agent 的 LLM 调用
messages = [
    {"role": "system", "content": "你是一个商旅知识专家。简洁回答，不超过500字。"},
    {"role": "user", "content": prompt}
]
response = await self.model(messages)  # 模型配置中 max_tokens 设为 2048
```

**预期收益**: LLM 生成时间从 ~15s 降至 ~5s。

### 2.2 端到端响应优化（目标: 95s → 30s）

**现状**: 端到端平均 95.1s/问题，主要耗时在意图识别（~10s）+ Agent 调度（~20s）+ 子 Agent 执行（~60s）。

#### 2.2.1 意图识别 Prompt 精简

**问题**: IntentionAgent 的 prompt 过长（~2000 字），LLM 处理慢。

**文件**: `agents/intention_agent.py`

**方案**:
1. 减少 prompt 中的示例和说明文字
2. 使用更简洁的输出格式
3. 将 Skills 元数据缓存而非每次动态加载

```python
# 当前：每次调用都加载 Skills 元数据
dynamic_skills_prompt = self.skill_loader.get_skill_prompt(skill_mapping)

# 优化：初始化时加载一次
def __init__(self, ...):
    ...
    self._skills_prompt_cache = None

async def reply(self, x):
    if self._skills_prompt_cache is None:
        self._skills_prompt_cache = self.skill_loader.get_skill_prompt(skill_mapping)
    ...
```

**预期收益**: 意图识别时间从 ~10s 降至 ~5s。

#### 2.2.2 并行调度优化

**问题**: 当前同优先级 Agent 使用 `asyncio.gather` 并行，但子 Agent 内部的 LLM 调用是串行等待响应。

**方案**: 确保所有子 Agent 的 LLM 调用真正并行（当前已是，但需验证无阻塞点）。

#### 2.2.3 流式响应

**问题**: 用户等待完整结果生成后才看到输出。

**方案**: 在 CLI 和 Web 端实现流式输出，先返回意图识别结果，再逐步返回子 Agent 结果。

```python
# cli.py 中使用流式输出
async def process_query(self, query: str):
    # 1. 先显示意图识别结果
    intention = await self.intention_agent.reply(msg)
    self.console.print(f"识别意图: ...")

    # 2. 逐个显示 Agent 结果
    for result in orchestration_result:
        self.console.print(f"{agent_name}: {result}")
```

**预期收益**: 用户感知等待时间从 95s 降至 ~15s（首字节时间）。

### 2.3 行程规划优化（目标: 186s → 60s）

**问题**: ItineraryPlanningAgent 响应时间 186s，且 JSON 解析偶尔失败。

#### 2.3.1 限制行程详细度

**文件**: `.claude/skills/plan-trip/script/agent.py`

**方案**: 在 prompt 中限制每日活动数量和描述长度。

```
【输出要求】
- 每日最多 3 个活动
- 每个活动描述不超过 100 字
- 总行程不超过 5 天
- 必须输出合法 JSON，不要在字符串值中使用未转义的引号
```

**预期收益**: 生成时间从 ~180s 降至 ~60s，JSON 解析成功率提升。

#### 2.3.2 JSON 输出强化

**问题**: LLM 输出的 JSON 中包含未转义的中文引号（如 `"description": 下午沿福堤步行...`）。

**方案**: 在 prompt 中增加 JSON 格式约束。

```
【JSON 格式要求】（严格遵守）
1. 所有字符串值必须用双引号包围
2. 字符串值内部的双引号必须转义为 \"
3. 不要在字符串值中使用换行符
4. 确保所有括号和引号配对完整
```

---

## 3. P1 - 代码质量优化

### 3.1 JSON 解析器增强

**文件**: `utils/json_parser.py`

**问题**: 测试中 ItineraryPlanningAgent 的 JSON 输出偶发解析失败（中文引号问题）。

**方案**: 增加中文引号修复策略。

```python
# 新增：修复中文引号
def fix_chinese_quotes(s: str) -> str:
    """将中文引号替换为英文引号"""
    s = s.replace('“', '"').replace('”', '"')  # ""
    s = s.replace('‘', "'").replace('’', "'")  # ''
    return s

# 在 robust_json_parse 中增加此策略
try:
    json_str_fixed = fix_chinese_quotes(json_str)
    result = json.loads(json_str_fixed)
    return result
except json.JSONDecodeError:
    pass
```

### 3.2 AgentScope 模型参数适配

**问题**: `temperature` 和 `max_tokens` 参数被 AgentScope 1.0.16 忽略。

**文件**: `config_agentscope.py`, 所有 Agent 的 `__init__`

**方案**: 检查 AgentScope 1.0.16 的正确参数传递方式。

```python
# 当前（参数被忽略）
model = OpenAIChatModel(
    model_name=LLM_CONFIG["model_name"],
    api_key=LLM_CONFIG["api_key"],
    client_kwargs={"base_url": LLM_CONFIG["base_url"]},
    temperature=0.7,  # 被忽略
    max_tokens=2000,  # 被忽略
)

# 优化：将参数放入 client_kwargs
model = OpenAIChatModel(
    model_name=LLM_CONFIG["model_name"],
    api_key=LLM_CONFIG["api_key"],
    client_kwargs={
        "base_url": LLM_CONFIG["base_url"],
        "default_headers": {},
    },
    # 或使用 generate_kwargs
    generate_kwargs={"temperature": 0.7, "max_tokens": 2000},
)
```

### 3.3 gRPC Keepalive 配置优化

**问题**: Milvus Lite 的 gRPC keepalive 配置导致 GOAWAY 警告。

**文件**: `.claude/skills/ask-question/script/agent.py`

**方案**: 调整 keepalive 参数或使用更保守的配置。

```python
# 当前配置导致 too_many_pings
_GRPC_MAX_MS = '2147483647'

# 优化：使用更保守的 keepalive 间隔
os.environ['GRPC_KEEPALIVE_TIME_MS'] = '600000'  # 10分钟
os.environ['GRPC_KEEPALIVE_TIMEOUT_MS'] = '20000'
```

---

## 4. P1 - 架构优化

### 4.1 记忆系统缓存层

**问题**: 每次查询都读取 JSON 文件，无缓存。

**文件**: `context/long_term_memory.py`

**方案**: 增加内存缓存层，减少文件 I/O。

```python
class LongTermMemory:
    def __init__(self, user_id, storage_path):
        ...
        self._cache = {}
        self._cache_loaded = False

    def _load_data(self):
        if self._cache_loaded:
            return self._cache
        # 从文件加载
        self._cache = self._read_json_file()
        self._cache_loaded = True
        return self._cache

    def _save_data(self, data):
        self._cache = data
        self._write_json_file(data)
```

### 4.2 懒加载优化 - 预热机制

**问题**: 首次调用 Agent 时加载延迟明显（RAG Agent ~3s）。

**文件**: `agents/lazy_agent_registry.py`

**方案**: 增加预热机制，在系统初始化后异步预加载常用 Agent。

```python
class LazyAgentRegistry:
    async def warmup(self, agent_names: list = None):
        """预热指定的 Agent（异步加载）"""
        if agent_names is None:
            agent_names = ["rag_knowledge", "event_collection"]

        tasks = []
        for name in agent_names:
            if name in self._skill_map and name not in self.cache:
                tasks.append(self._async_load(name))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
```

### 4.3 响应压缩

**问题**: 子 Agent 返回的 JSON 结果体积大，传输和解析耗时。

**方案**: 在 OrchestrationAgent 聚合结果时，裁剪冗余字段。

```python
def _aggregate_results(self, results, intention_data):
    ...
    for result in results:
        data = result["result"].get("data", {})
        # 裁剪 retrieved_documents 的 content 长度
        if "retrieved_documents" in data:
            for doc in data["retrieved_documents"]:
                doc["content"] = doc["content"][:100] + "..."
    ...
```

---

## 5. P2 - 测试框架优化

### 5.1 引入 pytest 框架

**现状**: 所有测试使用自定义脚本 + print 输出，无断言机制。

**方案**:

```python
# tests/test_intention_agent.py (改造后)
import pytest

@pytest.mark.asyncio
async def test_itinerary_planning(intention_agent):
    msg = Msg(name="User", content="我要从北京去上海出差3天", role="user")
    result = await intention_agent.reply(msg)
    data = json.loads(result.content)

    assert "itinerary_planning" in [i["type"] for i in data["intents"]]
    assert data["intents"][0]["confidence"] >= 0.8

@pytest.fixture
async def intention_agent():
    init_agentscope()
    model = OpenAIChatModel(...)
    return IntentionAgent(name="test", model=model)
```

### 5.2 LLM Mock 机制

**方案**: 使用 `unittest.mock` 或 `pytest-mock` 模拟 LLM 响应。

```python
@pytest.fixture
def mock_llm_response():
    return {
        "intents": [{"type": "itinerary_planning", "confidence": 0.95}],
        "agent_schedule": [{"agent_name": "event_collection", "priority": 1}]
    }

@pytest.mark.asyncio
async def test_intention_with_mock(monkeypatch, mock_llm_response):
    async def mock_model(*args, **kwargs):
        return MockResponse(json.dumps(mock_llm_response))

    monkeypatch.setattr(agent, "model", mock_model)
    ...
```

### 5.3 性能基准测试

**方案**: 建立性能基线，监控回归。

```python
# tests/test_performance.py
@pytest.mark.benchmark
async def test_rag_response_time(benchmark):
    result = await benchmark(agent.reply, query_msg)
    assert benchmark.stats["mean"] < 25.0  # 25s 基线

@pytest.mark.benchmark
async def test_intention_response_time(benchmark):
    result = await benchmark(agent.reply, query_msg)
    assert benchmark.stats["mean"] < 10.0  # 10s 基线
```

---

## 6. 优化实施路线图

### Phase 1 - 快速见效（1-2 天）

| 任务 | 文件 | 预期收益 |
|------|------|----------|
| Embedding 模型单例化 | ask-question/agent.py | RAG -2s |
| Milvus 预加载 | ask-question/agent.py | RAG -1s |
| RAG max_tokens 限制 | ask-question/agent.py | RAG -10s |
| 行程规划 prompt 精简 | plan-trip/agent.py | 行程规划 -120s |
| JSON 中文引号修复 | utils/json_parser.py | 解析成功率 +5% |

**Phase 1 预期**: RAG 23s → 10s, 行程规划 186s → 60s, 端到端 95s → 50s

### Phase 2 - 架构优化（3-5 天）

| 任务 | 文件 | 预期收益 |
|------|------|----------|
| RAG 结果缓存 | ask-question/agent.py | 重复查询 <1s |
| 意图识别 prompt 精简 | intention_agent.py | 意图识别 -5s |
| 记忆系统缓存层 | long_term_memory.py | 减少文件 I/O |
| 流式响应 | cli.py, server/ | 感知延迟 -80s |
| AgentScope 参数适配 | config_agentscope.py | 消除警告 |

**Phase 2 预期**: 端到端 50s → 25s, 首字节时间 <15s

### Phase 3 - 质量保障（5-7 天）

| 任务 | 文件 | 预期收益 |
|------|------|----------|
| pytest 框架改造 | tests/ | 自动化断言 |
| LLM Mock 机制 | tests/ | 离线测试 |
| 性能基准测试 | tests/test_performance.py | 回归监控 |
| Web API 测试 | tests/test_server.py | 覆盖率 +30% |
| CI/CD 集成 | .github/workflows/ | 自动化测试 |

---

## 7. 优化效果预估

| 指标 | 当前值 | Phase 1 | Phase 2 | Phase 3 |
|------|--------|---------|---------|---------|
| RAG 响应时间 | 23.3s | 10s | 5s (缓存命中 <1s) | 5s |
| 意图识别时间 | ~10s | 8s | 5s | 5s |
| 行程规划时间 | 186s | 60s | 45s | 45s |
| 端到端平均时间 | 95.1s | 50s | 25s | 25s |
| JSON 解析成功率 | ~90% | 95% | 98% | 98% |
| 测试覆盖率 | 50% | 50% | 55% | 80% |
| 首字节时间 | 95s | 50s | 15s | 15s |

---

## 8. 风险与注意事项

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| LLM 输出不稳定 | prompt 修改可能影响意图识别准确率 | 修改后回归测试 |
| 缓存一致性 | RAG 缓存可能导致返回过期数据 | 设置 TTL 过期机制 |
| max_tokens 过小 | 限制 token 数可能导致回答不完整 | 监控回答截断率 |
| AgentScope 版本兼容 | 参数适配可能因版本变化而失效 | 锁定 agentscope==1.0.16 |

---

## 9. 结论

本优化方案分三个阶段，从性能、架构、质量三个维度提升系统：

- **Phase 1** 聚焦快速见效的性能优化，预计端到端响应从 95s 降至 50s
- **Phase 2** 通过缓存和流式响应进一步优化至 25s，并改善用户体验
- **Phase 3** 建立完善的测试体系，保障长期可维护性

建议优先实施 Phase 1 中的 **RAG max_tokens 限制** 和 **行程规划 prompt 精简**，这两项改动最小、收益最大。
