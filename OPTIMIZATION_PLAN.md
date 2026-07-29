# 简单技能响应加速方案

## 问题现状

当前处理一个请求的标准流程：

```
用户输入 → 长期记忆摘要(LLM) → 意图识别(LLM) → 编排调度 → 子Agent执行(LLM) → 结果聚合
```

以"记一笔打车费50元"为例：

| 步骤 | 操作 | LLM调用 | 耗时 |
|------|------|:-------:|------|
| 1 | 长期记忆摘要 | 1次 | 2-5s |
| 2 | 意图识别 | 1次 | 2-8s |
| 3 | expense-tracker执行 | 1次 | 2-5s |
| **合计** | | **3次** | **6-18秒** |

**核心矛盾**：记一笔账、查个天气这种简单操作，却要等3次LLM调用。

---

## 方案一：规则快速路径（推荐）

**核心思想**：在意图识别之前加一层规则匹配，命中的直接走快速通道，跳过LLM意图识别。

### 1.1 新增快速意图路由器

在 `agents/` 下新增 `fast_router.py`：

```python
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class FastMatch:
    """快速匹配结果"""
    intent: str           # 意图类型
    skill: str            # 对应skill名
    confidence: float     # 置信度
    extracted_params: dict  # 提取的参数

class FastRouter:
    """规则快速路由器 - 在LLM意图识别前尝试匹配"""

    # 高置信度模式列表
    PATTERNS = [
        # 记账类
        {
            "intent": "expense_tracking",
            "skill": "expense-tracker",
            "patterns": [
                r"记[一]?[笔]?[：:]?\s*(.+?)\s*(\d+(?:\.\d+)?)\s*[元块钱]",
                r"[花用]了?\s*(\d+(?:\.\d+)?)\s*[元块钱].*?(.+)",
                r"打车[费花]?\s*(\d+)",
                r"餐[费饮]\s*(\d+)",
                r"住宿[费花]?\s*(\d+)",
            ],
            "extract": self._extract_expense,
        },
        # 天气查询
        {
            "intent": "information_query",
            "skill": "query-info",
            "patterns": [
                r"(.{2,10}?)[的]?天气",
                r"天气[怎么样如何查询查]",
                r"[今明后][天日].*?天气",
                r"温度[多少几度]",
            ],
            "extract": self._extract_weather,
        },
        # 汇率查询
        {
            "intent": "currency_conversion",
            "skill": "currency-converter",
            "patterns": [
                r"(\d+(?:\.\d+)?)\s*([美元人民币日元欧元英镑港币韩元])\s*[兑换换比]\s*([美元人民币日元欧元英镑港币韩元])",
                r"([美元人民币日元欧元英镑港币韩元])[兑换换].*?([美元人民币日元欧元英镑港币韩元])",
                r"汇率",
            ],
            "extract": self._extract_currency,
        },
        # 简单翻译（明确指定了语言的）
        {
            "intent": "translation",
            "skill": "translation",
            "patterns": [
                r"翻译成(英文|日文|韩文|法文|德文|中文|英文|日语|韩语|法语|德语|中文)",
                r"用(英文|日文|韩文|法文|德文|中文|日语|韩语|法语|德语)怎么说",
                r"translate.*?to\s+(english|chinese|japanese|korean|french|german)",
            ],
            "extract": self._extract_translation,
        },
    ]

    def match(self, query: str) -> Optional[FastMatch]:
        """尝试快速匹配，返回None表示需要走LLM"""
        for config in self.PATTERNS:
            for pattern in config["patterns"]:
                m = re.search(pattern, query, re.IGNORECASE)
                if m:
                    params = config["extract"](m, query)
                    if params:
                        return FastMatch(
                            intent=config["intent"],
                            skill=config["skill"],
                            confidence=0.9,
                            extracted_params=params
                        )
        return None
```

### 1.2 修改 OrchestrationAgent 调度流程

在 `orchestration_agent.py` 的 `process` 方法中：

```python
async def process(self, query: str, context: dict) -> AsyncGenerator:
    # 新增：快速路径
    fast_match = self.fast_router.match(query)

    if fast_match:
        # 快速路径：跳过意图识别LLM，直接执行对应skill
        yield self._make_event("fast_path", f"快速匹配: {fast_match.skill}")

        agent = self.registry.get_agent(fast_match.skill)
        result = await agent.execute_fast(
            query=query,
            params=fast_match.extracted_params,
            context=context
        )
        yield self._make_event("result", result)
        return

    # 慢速路径：原有LLM意图识别流程
    intention = await self.intention_agent.analyze(query, context)
    # ... 后续逻辑不变
```

### 1.3 子Agent新增快速执行方法

以 `ExpenseTrackerAgent` 为例：

```python
class ExpenseTrackerAgent:
    async def execute_fast(self, query: str, params: dict, context: dict) -> str:
        """快速执行 - 跳过LLM解析，直接使用提取好的参数"""
        action = params.get("action", "record")

        if action == "record":
            expense = self._build_expense(params)
            self._save_expense(expense, context)
            return f"已记录: {expense['category']} {expense['amount']}元"

        elif action == "query":
            summary = self._query_summary(params)
            return summary

        # 兜底：走原有LLM路径
        return await self.execute(query, context)

    def _build_expense(self, params: dict) -> dict:
        """从规则提取的参数构建费用记录"""
        return {
            "category": params.get("category", "其他"),
            "amount": float(params.get("amount", 0)),
            "description": params.get("description", ""),
            "timestamp": datetime.now().isoformat(),
        }
```

### 1.4 天气查询的快速路径

`InformationQueryAgent` 天气查询本身已经不需要LLM，但需要让它在快速路径下直接执行：

```python
class InformationQueryAgent:
    async def execute_fast(self, query: str, params: dict, context: dict) -> str:
        if params.get("type") == "weather":
            city = params.get("city", "auto")
            return await self._get_weather(city)
        return await self.execute(query, context)
```

### 1.5 预期效果

| 场景 | 原耗时 | 优化后 | 减少 |
|------|--------|--------|------|
| 记一笔打车费50元 | 6-18s (3次LLM) | 2-5s (1次LLM意图识别) | 60-70% |
| 北京天气怎么样 | 4-12s (2次LLM) | 1-2s (0次LLM) | 80-90% |
| 100美元换人民币 | 6-18s (3次LLM) | 1-2s (0次LLM) | 85-95% |
| 规划北京三日游 | 8-20s (3次LLM) | 8-20s (3次LLM) | 不变 |

---

## 方案二：意图识别轻量化

**核心思想**：优化LLM意图识别本身的耗时。

### 2.1 精简意图识别Prompt

当前prompt包含所有10个skill的完整描述，可以精简为关键词映射表：

```python
# 原prompt约2000 tokens，精简后约500 tokens
LIGHTWEIGHT_PROMPT = """你是意图分类器。根据用户输入，返回JSON。

意图类型：
- expense_tracking: 记账/费用相关（关键词：记账、花了、打车费、餐费）
- information_query: 天气/信息查询（关键词：天气、温度、怎么样）
- currency_conversion: 汇率（关键词：汇率、兑换、美元、人民币）
- translation: 翻译（关键词：翻译、怎么说、translate）
- preference: 偏好设置（关键词：喜欢、偏好、常坐）
- memory_query: 历史查询（关键词：之前、上次、去过哪）
- rag_knowledge: 政策问答（关键词：标准、规定、怎么办）
- itinerary_planning: 行程规划（关键词：规划、行程、安排）
- event_collection: 要素提取（关键词：我要去、从XX到XX）
- visa_info: 签证（关键词：签证、免签、入境）

用户输入：{query}

返回：{"intents": ["类型"], "confidence": 0.0-1.0}
"""
```

### 2.2 使用更快的模型做意图识别

在 `config.py` 中增加意图识别专用模型配置：

```python
# 意图识别用轻量模型（如qwen-turbo、glm-4-flash等）
INTENTION_MODEL = os.getenv("ALIGO_INTENTION_MODEL", "qwen-turbo")
INTENTION_BASE_URL = os.getenv("ALIGO_INTENTION_BASE_URL", BASE_URL)
```

### 2.3 意图识别结果缓存

对相同或相似query缓存意图识别结果：

```python
class IntentionCache:
    def __init__(self, ttl=300):  # 5分钟过期
        self.cache = {}
        self.ttl = ttl

    def get(self, query: str) -> Optional[dict]:
        # 模糊匹配：去除数字/时间后匹配
        normalized = self._normalize(query)
        if normalized in self.cache:
            entry = self.cache[normalized]
            if time.time() - entry["ts"] < self.ttl:
                return entry["result"]
        return None

    def _normalize(self, query: str) -> str:
        # "记一笔打车费50元" -> "记一笔打车费X元"
        return re.sub(r'\d+', 'X', query).strip()
```

---

## 方案三：记忆摘要按需触发

**核心思想**：简单查询不需要加载历史记忆。

### 3.1 修改CLI入口

在 `cli.py` 的 `_get_long_term_summary` 中增加跳过逻辑：

```python
async def _get_long_term_summary(self, query: str) -> str:
    # 快速意图预判，简单查询跳过记忆摘要
    if self._is_simple_query(query):
        return ""

    # 原有逻辑
    return await self.memory_manager.get_long_term_summary_async()

def _is_simple_query(self, query: str) -> bool:
    """判断是否为简单查询"""
    simple_patterns = [
        r"记.*[费花].*\d+",      # 记账
        r"天气",                   # 天气
        r"汇率|兑换|换.*人民币",   # 汇率
        r"翻译.*成|用.*怎么说",    # 翻译
    ]
    return any(re.search(p, query) for p in simple_patterns)
```

### 3.2 修改MemoryQueryAgent避免重复调用

```python
class MemoryQueryAgent:
    async def execute(self, query: str, context: dict) -> str:
        # 从context获取已有的摘要，避免重复LLM调用
        summary = context.get("long_term_summary")
        if not summary:
            summary = await self.memory_manager.get_long_term_summary_async()

        # 用LLM生成回答
        response = await self.model(f"基于以下记忆回答问题：\n{summary}\n\n问题：{query}")
        return response
```

---

## 实施路线图

### Phase 1：快速路径（1-2天）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 实现 FastRouter | 新增 `agents/fast_router.py` | 4h |
| 修改 OrchestrationAgent | `agents/orchestration_agent.py` | 2h |
| ExpenseTrackerAgent 快速执行 | `.claude/skills/expense-tracker/script/agent.py` | 2h |
| InformationQueryAgent 快速执行 | `.claude/skills/query-info/script/agent.py` | 1h |
| CurrencyConverterAgent 快速执行 | `.claude/skills/currency-converter/script/agent.py` | 2h |

### Phase 2：意图识别优化（1天）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 精简prompt | `agents/intention_agent.py` | 2h |
| 意图缓存 | 新增 `utils/intention_cache.py` | 2h |
| 可选：配置轻量模型 | `config.py` | 1h |

### Phase 3：记忆优化（0.5天）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| CLI跳过简单查询摘要 | `cli.py` | 1h |
| context传递摘要 | `agents/orchestration_agent.py` + 各子Agent | 2h |

---

## 风险与兜底

| 风险 | 应对 |
|------|------|
| 规则匹配误判 | 置信度阈值 < 0.85 时回退LLM路径 |
| 用户表达多样覆盖不全 | 规则+LLM双通道，规则未命中不影响原流程 |
| 正则提取参数不完整 | `execute_fast` 内部做参数校验，缺失则回退 |

**兜底策略**：所有快速路径失败时，自动回退到原有LLM流程，保证功能正确性。

---

## 预期收益总结

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 记账响应时间 | 6-18s | 2-5s |
| 天气查询响应时间 | 4-12s | 1-2s |
| 汇率查询响应时间 | 6-18s | 1-2s |
| 简单翻译响应时间 | 6-18s | 2-5s |
| 复杂任务（行程规划） | 8-20s | 8-20s（不变） |
| 每请求LLM调用次数 | 2-3次 | 0-1次（简单）/ 1-2次（复杂） |
