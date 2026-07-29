# Aligo 旅行助手 - 性能优化实施方案

> 目标：针对 "我明天要从广州去北京" 等简单行程查询，将端到端响应时间从 60s+ 降至 15s 以内（首字节 <3s）。
> 范围：CLI 入口、意图识别、编排调度、Skill 插件、配置参数。
> 原则：先快速见效，再架构优化；每项改动可独立回滚；优先减少 LLM 调用次数和 token 输出量。

---

## 1. 现状诊断

### 1.1 请求链路耗时拆解

| 阶段 | 主要代码位置 | 当前耗时 | 瓶颈说明 |
|------|-------------|---------|---------|
| 快速路由 | `agents/intention_agent.py:288-301` | ~1ms | "从 A 去 B" 未命中规则，需走 LLM |
| 意图识别 LLM | `agents/intention_agent.py:438` | 10-20s | Prompt 约 2000 字；JSON 解析失败会内部重试 |
| 事项收集 LLM | `.claude/skills/event-collection/script/agent.py:40-148` | 5-15s | 提取出发地/目的地/日期也走 LLM |
| 火车票查询 | `.claude/skills/train-ticket/script/agent.py:124-410` | 3-10s | 冷启动需下载 12306 站点表；调用 12306 余票接口 |
| 行程规划 LLM | `.claude/skills/plan-trip/script/agent.py:32-204` | 30-50s | `max_tokens=8192`，输出过度详细的结构化行程 |
| CLI 轮询尾延迟 | `cli.py:251-264` | 0-5s | 每 5s 超时轮询 `result_queue` |
| 冷启动杂项 | `agents/lazy_agent_registry.py`、`utils/skill_loader.py` | 2-5s | 动态导入、重复解析 SKILL.md |
| **合计** | - | **60-90s** | - |

### 1.2 根因总结

1. **过度使用 LLM**：出发地/目的地/日期提取、简单意图判断都依赖 LLM。
2. **行程规划 token 过大**：`max_tokens=8192` 对简单查询严重过量。
3. **串行依赖**：`itinerary_planning` 必须等 `event_collection` 和 `train_ticket` 完成后才执行。
4. **缺少快速路径**：没有把"出发地+目的地+日期"这种简单模式直接处理掉。
5. **资源重复加载**：每个 Agent 独立创建 `SkillLoader`，重复读取 YAML；Agent 首次调用时才动态导入。
6. **CLI 交互不实时**：5 秒轮询让用户感知更慢。

---

## 2. 优化目标

| 指标 | 当前值 | 目标值 | 备注 |
|------|--------|--------|------|
| 简单行程查询端到端时间 | 60-90s | <15s | 含 12306 查询 |
| 首字节时间（用户看到第一条反馈） | ~10-20s | <3s | 意图识别/快速路径完成后即显示 |
| 行程规划 LLM 调用次数 | 1 次/查询 | 简单查询 0 次 | 仅复杂多日程查询才触发 |
| `max_tokens` 实际使用 | 8192 | 按场景 512-2048 | 避免模型过度生成 |
| 重复 SKILL.md 解析 | 多次/查询 | 1 次/进程 | 全局缓存 |
| Agent 冷启动延迟 | 首次查询时发生 | 初始化阶段预热 | 用户无感知 |

---

## 3. 优化方案总览

按优先级分为三个阶段：

- **Phase 1（快速见效）**：配置调优 + 简单行程快速路径 + SkillLoader 缓存 + CLI 轮询优化。预期端到端降至 20-30s。
- **Phase 2（架构优化）**：Agent 预热、按场景拆分 token 限制、结果流式推送、轻量意图缓存。预期端到端降至 10-15s。
- **Phase 3（兜底与监控）**：熔断/降级策略、性能基准测试、关键路径日志。保障稳定性。

---

## 4. Phase 1 - 快速见效（预计 1-2 天）

### 4.1 配置层：按场景设置 max_tokens

**文件**：`config.py`

**问题**：当前所有 LLM 调用统一使用 `max_tokens: 8192`。

**改动**：

```python
LLM_CONFIG = {
    # ... 现有字段保持不变
    "max_tokens": 8192,  # 保持默认兼容
}

# 新增：按场景 token 预算
SCENARIO_TOKENS = {
    "intention": 1024,        # 意图识别只需输出 JSON
    "event_collection": 1024, # 事项提取 JSON
    "itinerary": 2048,        # 简单行程规划
    "itinerary_complex": 4096,# 多日程复杂行程
    "rag": 2048,              # 知识库问答
    "chat": 1024,             # 闲聊/总结
}
```

**收益**：行程规划输出 token 减少约 75%，生成时间从 30-50s 降至 8-15s。

**风险**：复杂行程可能截断。缓解：通过 `itinerary_complex` 分支区分。

---

### 4.2 新增"简单行程"快速路径

**文件**：`agents/intention_agent.py`（在 `_fast_match` 中新增规则）

**问题**："我明天要从广州去北京"没有"火车/高铁/票"等词，无法命中现有规则。

**改动**：

```python
# 在 _fast_match 函数中新增一段简单行程规则
_TRAVEL_PATTERNS = [
    re.compile(r"(?:我)?(?:明天|后天|今天|(?:\d{1,2}月)?\d{1,2}[日号])?(?:想|要|准备|打算)?(?:从)?\s*([一-龥]{2,6})\s*(?:去|到|往|至)\s*([一-龥]{2,6})"),
    re.compile(r"(?:我)?(?:想|要|准备|打算)?(?:去|到|往|至)\s*([一-龥]{2,6})\s*(?:玩|旅游|出差|旅行)"),
]

def _fast_match(query: str) -> Optional[dict]:
    # ... 保持现有规则不变

    # 新增：简单行程规则
    date_match = re.search(r"(明天|后天|今天|\d{1,2}月\d{1,2}[日号]|\d{4}-\d{1,2}-\d{1,2})", q)
    date_str = date_match.group(1) if date_match else ""

    for p in _TRAVEL_PATTERNS:
        m = p.search(q)
        if m:
            from_city, to_city = m.group(1), m.group(2)
            return {
                "reasoning": "规则匹配: 简单行程意图",
                "intents": [
                    {"type": "itinerary_planning", "confidence": 0.92, "description": "简单行程规划", "reason": "匹配出发地+目的地+日期"}
                ],
                "key_entities": {"origin": from_city, "destination": to_city, "date": date_str},
                "rewritten_query": q,
                "agent_schedule": [
                    {"agent_name": "event_collection", "priority": 1, "reason": "提取行程要素", "expected_output": "结构化行程信息"},
                    {"agent_name": "train_ticket", "priority": 1, "reason": "查询火车票", "expected_output": "车次信息"},
                    {"agent_name": "itinerary_planning", "priority": 2, "reason": "规划行程", "expected_output": "简要行程建议"},
                ],
                "fast_travel": {"from": from_city, "to": to_city, "date": date_str},
            }

    return None
```

**收益**：
- 常见句式直接命中规则，跳过意图识别 LLM，节省 10-20s。
- 同时把 `fast_travel` 参数透传给下游 Agent，避免 `event_collection` 再次 LLM 提取。

**风险**：规则覆盖不全。缓解：保留 LLM 兜底路径；规则未命中时走原流程。

---

### 4.3 event-collection 支持 fast_travel 参数

**文件**：`.claude/skills/event-collection/script/agent.py`

**问题**：即使 `_fast_match` 已经提取了出发地/目的地/日期，`event_collection` 仍会用 LLM 重新提取一遍。

**改动**：

```python
async def reply(self, x):
    # ... 解析 content
    fast_travel = data.get("fast_travel")

    # 如果已有 fast_travel 参数，直接构造结果，不走 LLM
    if fast_travel and fast_travel.get("from") and fast_travel.get("to"):
        from datetime import datetime, timedelta
        date_str = fast_travel.get("date", "")
        # 解析相对日期
        if date_str == "明天":
            start_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_str == "后天":
            start_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        elif re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            start_date = date_str
        else:
            start_date = datetime.now().strftime("%Y-%m-%d")

        return Msg(name=self.name, content=json.dumps({
            "origin": fast_travel["from"],
            "destination": fast_travel["to"],
            "start_date": start_date,
            "end_date": None,
            "duration_days": 1,
            "return_location": fast_travel["from"],
            "trip_purpose": "旅游",
            "missing_info": ["返程日期", "行程目的"],
            "extracted_count": 5,
            "summary": f"{fast_travel['from']}到{fast_travel['to']}，{start_date}出发"
        }, ensure_ascii=False), role="assistant")

    # ... 原有 LLM 路径保留
```

**收益**：简单查询跳过 `event_collection` 的 LLM，节省 5-15s。

---

### 4.4 SkillLoader 全局缓存

**文件**：`utils/skill_loader.py`

**问题**：每个 Agent 独立 `new SkillLoader()`，重复 `os.listdir` + `yaml.safe_load`。

**改动**：

```python
# 模块级缓存
_SKILL_PROMPT_CACHE = None
_SKILL_CONTENT_CACHE = {}

def get_skill_prompt_cached(skill_loader_instance, skill_mapping=None):
    global _SKILL_PROMPT_CACHE
    if _SKILL_PROMPT_CACHE is None:
        _SKILL_PROMPT_CACHE = skill_loader_instance.get_skill_prompt(skill_mapping)
    return _SKILL_PROMPT_CACHE

def get_skill_content_cached(skill_loader_instance, skill_name: str):
    global _SKILL_CONTENT_CACHE
    if skill_name not in _SKILL_CONTENT_CACHE:
        _SKILL_CONTENT_CACHE[skill_name] = skill_loader_instance.get_skill_content(skill_name)
    return _SKILL_CONTENT_CACHE[skill_name]
```

在 `IntentionAgent.__init__` 和 `ItineraryPlanningAgent.__init__` 中调用缓存版本。

**收益**：单次查询减少 2-4 次 YAML 解析，节省 50ms-2s（Windows 下更明显）。

---

### 4.5 CLI 轮询改为短超时 + 即时事件

**文件**：`cli.py:251-264`

**问题**：`await asyncio.wait_for(result_queue.get(), timeout=5.0)` 导致尾延迟最高 5s。

**改动**：

```python
# 从 5.0s 改为 0.2s
while not task.done():
    try:
        item = await asyncio.wait_for(result_queue.get(), timeout=0.2)
        # ... 处理 item
    except asyncio.TimeoutError:
        continue
```

**收益**：尾延迟从 0-5s 降至 0-0.2s。

---

### 4.6 train-ticket 站点表预下载

**文件**：`agents/lazy_agent_registry.py` 或 `cli.py` 初始化流程

**问题**：首次调用 `train_ticket` 时同步下载 `stations.json`，阻塞事件循环。

**改动**：在系统初始化阶段异步预热：

```python
# cli.py initialize_system 末尾
from .claude.skills.train-ticket.script.agent import _load_stations
await asyncio.to_thread(_load_stations)
```

**收益**：首问时不再阻塞在站点表下载。

---

## 5. Phase 2 - 架构优化（预计 3-5 天）

### 5.1 Agent 预热机制

**文件**：`agents/lazy_agent_registry.py`

**改动**：

```python
async def warmup(self, agent_names: List[str] = None):
    if agent_names is None:
        agent_names = ["event_collection", "train_ticket", "itinerary_planning"]
    tasks = []
    for name in agent_names:
        if name in self._skill_map and name not in self.cache:
            tasks.append(self._async_load(name))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

在 `cli.py` 初始化后调用 `await lazy_registry.warmup()`。

**收益**：动态导入开销从首问转移到启动阶段。

---

### 5.2 按查询复杂度选择 token 预算

**文件**：`.claude/skills/plan-trip/script/agent.py`

**改动**：根据行程天数选择 `max_tokens`：

```python
from config import SCENARIO_TOKENS

# 从 all_info 中判断行程天数
duration = context_info.get("duration_days", 1)
if duration is None or duration <= 1:
    max_tokens = SCENARIO_TOKENS["itinerary"]
else:
    max_tokens = SCENARIO_TOKENS["itinerary_complex"]

response = await self.model(
    [{"role": "user", "content": prompt}],
    max_tokens=max_tokens  # 需要确认 AgentScope/OpenAIChatModel 支持此参数传入
)
```

**收益**：一日游等简单查询输出更短、更快。

---

### 5.3 简单行程直接返回，不调用行程规划 LLM

**文件**：`agents/orchestration_agent.py`

**改动**：当 `itinerary_planning` 的输入只有单日、单目的地时，直接构造简要响应：

```python
async def _execute_agent(self, agent_name, context, ...):
    if agent_name == "itinerary_planning":
        event_data = self._find_previous_result(previous_results, "event_collection")
        if self._is_simple_trip(event_data):
            return self._build_simple_itinerary(event_data, previous_results)
    # ... 原有路径
```

简单行程定义：
- 只有出发地、目的地、start_date
- duration_days 为空或 <= 1
- 没有明确景点/酒店/餐饮需求

**收益**：大量日常查询跳过最慢的行程规划 LLM。

---

### 5.4 意图识别缓存

**文件**：`agents/intention_agent.py`

**改动**：对 `_fast_match` 命中规则的查询结果做短期缓存（已部分实现 `@cached`，但规则命中的路径未缓存）：

```python
# 在 _fast_match 命中后，也使用相同的缓存 key 存储
if fast:
    # 当前 @cached 装饰器会缓存整个 reply 结果
    # 无需额外改动，但需确保 fast 路径在 @cached 统计范围内
    return Msg(...)
```

如果希望缓存未命中规则但结果稳定的 LLM 输出，可在 `@cached` 之外增加基于 query hash 的内存缓存，TTL 5-10 分钟。

---

### 5.5 流式结果推送（Web + CLI）

**文件**：`cli.py`、`server/routes/chat.py`

**改动**：
- CLI 端在 `_display_single_agent_result` 中每收到一个 Agent 结果就立即打印，而非等全部完成。
- Web 端 SSE 已流式，但可考虑把"意图识别完成"也作为第一个 SSE 事件推送。

**收益**：用户感知等待时间大幅下降（首字节 <3s）。

---

## 6. Phase 3 - 兜底与监控

### 6.1 性能基准测试

**文件**：`tests/test_performance.py`（新增）

```python
import pytest
import time

@pytest.mark.asyncio
async def test_simple_itinerary_latency(intention_agent, orchestrator):
    query = "我明天要从广州去北京"
    t0 = time.time()
    msg = Msg(name="User", content=query, role="user")
    intention = await intention_agent.reply(msg)
    # ... 执行编排
    elapsed = time.time() - t0
    assert elapsed < 15.0, f"Simple itinerary took {elapsed:.1f}s"
```

### 6.2 关键路径日志

**文件**：各 Agent 已有时序日志，建议统一格式并增加阶段标识：

```python
logger.info(f"[PERF] stage=intention duration={duration_ms}ms query_hash={hash}")
logger.info(f"[PERF] stage=event_collection duration={duration_ms}ms cached={is_cached}")
logger.info(f"[PERF] stage=train_ticket duration={duration_ms}ms api_hit={hit}")
logger.info(f"[PERF] stage=itinerary duration={duration_ms}ms tokens={tokens}")
```

### 6.3 12306 降级策略

**文件**：`.claude/skills/train-ticket/script/agent.py`

**改动**：当 12306 API 失败时，返回友好提示并继续行程规划，而不是让整体失败：

```python
if not ticket_result.get("query_success"):
    return {
        "query_type": "余票查询",
        "query_success": False,
        "results": {"message": "12306 接口暂时不可用，将基于常见车次给出建议。"},
        "fallback": True
    }
```

---

## 7. 实施顺序与回滚策略

| 顺序 | 改动 | 影响范围 | 回滚方式 |
|------|------|---------|---------|
| 1 | `config.py` 增加 `SCENARIO_TOKENS` | 全局 | 删除新增字典即可 |
| 2 | `IntentionAgent._fast_match` 新增简单行程规则 | `agents/intention_agent.py` | 删除新增规则块 |
| 3 | `event-collection` 支持 `fast_travel` | `.claude/skills/event-collection/script/agent.py` | 删除 fast 分支 |
| 4 | `SkillLoader` 全局缓存 | `utils/skill_loader.py` | 移除缓存函数 |
| 5 | CLI 轮询超时改为 0.2s | `cli.py` | 改回 5.0s |
| 6 | train-ticket 站点表预下载 | `cli.py` 初始化 | 删除预热代码 |
| 7 | Agent 预热机制 | `agents/lazy_agent_registry.py` | 不调用 warmup |
| 8 | 简单行程跳过 itinerary LLM | `agents/orchestration_agent.py` | 删除简单行程分支 |
| 9 | 按复杂度选择 token | `.claude/skills/plan-trip/script/agent.py` | 移除 token 参数 |
| 10 | 性能基准测试 | 新增测试文件 | 删除测试文件 |

---

## 8. 预期收益汇总

| 优化项 | 预计节省时间 | 实施后预期总耗时 |
|--------|-------------|----------------|
| 简单行程规则命中 | 10-20s | 50-70s |
| event-collection fast 路径 | 5-15s | 35-55s |
| max_tokens 限制 + 简单行程跳过 LLM | 20-40s | 10-25s |
| SkillLoader 缓存 + CLI 轮询优化 | 2-7s | 8-20s |
| Agent 预热 + 站点表预下载 | 2-5s（首问） | 8-18s |
| **最终目标** | - | **<15s** |

---

## 9. 待确认问题

1. `OpenAIChatModel` 是否支持在 `await self.model(messages, max_tokens=...)` 调用时传入 `max_tokens`？如果不支持，需要通过修改 `generate_kwargs` 或封装一个 `model_with_budget()` 实现。
2. 项目中 `@cached` 装饰器（`cache.decorators.cached`）的实现是否对 `Msg` 对象做了可 hash 处理？需要确认缓存 key 逻辑。
3. 12306 站点表下载是否允许在初始化阶段进行？需确认网络环境是否允许。
4. 是否接受"简单行程不调用 LLM，直接返回固定模板"的行为？这可能损失一些个性化，但能极大提速。

---

## 10. 下一步建议

1. 确认上述 4 个待确认问题。
2. 从 Phase 1 开始实施：先做 `config.py` + `_fast_match` + `event-collection` fast 路径，这三项改动最小、收益最大。
3. 跑 `python cli.py` 对比优化前后耗时。
4. 补充 `tests/test_performance.py` 作为回归保护。
