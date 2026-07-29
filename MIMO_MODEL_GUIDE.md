# 小米 MiMo 模型对比与选择指南

## 当前项目配置

根据 `.env` 文件，项目当前使用：
- **模型**: `mimo-v2.5-pro`
- **API地址**: `https://api.xiaomimimo.com/v1`

---

## MiMo 模型系列（基于公开信息）

> **注意**: 以下信息基于公开资料整理，具体性能数据请以小米官方文档为准。

### 模型层级推测

| 模型名称 | 定位 | 预期特点 | 适用场景 |
|----------|------|----------|----------|
| **mimo-v2.5-pro** | 旗舰版 | 最强推理能力，响应较慢 | 复杂推理、行程规划、知识问答 |
| **mimo-v2.5-turbo** | 速度版 | 平衡速度与质量 | 通用对话、中等复杂度任务 |
| **mimo-v2.5-lite** | 轻量版 | 最快响应，能力有限 | 简单意图识别、格式化输出 |
| **mimo-v2-pro** | 旧旗舰 | 成熟稳定 | 备选方案 |

### 意图识别场景推荐

对于本项目的**意图识别**任务，推荐测试以下模型：

```
# .env 配置示例（意图识别专用）
ALIGO_INTENTION_MODEL=mimo-v2.5-turbo
ALIGO_INTENTION_BASE_URL=https://api.xiaomimimo.com/v1
```

---

## 如何获取最新模型列表

### 方法1：查看小米MiMo官方文档

访问小米MiMo开放平台，查看支持的模型列表：
- 官网: https://xiaomimimo.com
- API文档: https://api.xiaomimimo.com/docs

### 方法2：调用API获取模型列表

```bash
# 使用curl测试
curl https://api.xiaomimimo.com/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 方法3：Python脚本测试

```python
import requests
import time

# 测试不同模型的响应速度
models = [
    "mimo-v2.5-pro",
    "mimo-v2.5-turbo",
    "mimo-v2.5-lite",
    "mimo-v2-pro",
]

api_key = "YOUR_API_KEY"
base_url = "https://api.xiaomimimo.com/v1"

test_prompt = "请用JSON格式返回：{\"intent\": \"weather_query\"}"

for model in models:
    start = time.time()
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": 100,
                "temperature": 0.1
            },
            timeout=30
        )
        elapsed = time.time() - start
        if response.status_code == 200:
            print(f"{model}: {elapsed:.2f}s ✓")
        else:
            print(f"{model}: HTTP {response.status_code}")
    except Exception as e:
        print(f"{model}: Error - {e}")
```

---

## 意图识别模型选择策略

### 策略A：双模型架构（推荐）

```python
# config.py 新增
LLM_CONFIG = {
    # 主模型：用于复杂任务
    "model_name": os.environ.get("ALIGO_MODEL_NAME", "mimo-v2.5-pro"),
    "base_url": os.environ.get("ALIGO_BASE_URL", "https://api.xiaomimimo.com/v1"),
}

# 意图识别专用：轻量快速模型
INTENTION_CONFIG = {
    "model_name": os.environ.get("ALIGO_INTENTION_MODEL", "mimo-v2.5-turbo"),
    "base_url": os.environ.get("ALIGO_INTENTION_BASE_URL", "https://api.xiaomimimo.com/v1"),
    "temperature": 0.1,  # 低温度，确定性输出
    "max_tokens": 500,    # 限制输出长度
}
```

### 策略B：规则+LLM混合

```python
# 简单意图用规则，复杂意图用LLM
class IntentionAgent:
    async def analyze(self, query: str) -> dict:
        # 1. 先尝试规则匹配
        fast_match = self.fast_router.match(query)
        if fast_match and fast_match.confidence > 0.85:
            return fast_match.to_intention_result()
        
        # 2. 规则未命中，用轻量LLM
        if self.use_lightweight_model:
            result = await self._call_llm(query, model="mimo-v2.5-turbo")
        else:
            result = await self._call_llm(query, model="mimo-v2.5-pro")
        
        return result
```

---

## 性能测试建议

### 测试指标

1. **响应时间**: 从请求发出到收到完整响应
2. **首Token延迟**: 从请求发出到收到第一个token（流式场景）
3. **准确率**: 意图识别正确率
4. **稳定性**: 连续调用的成功率

### 测试用例

```python
TEST_CASES = [
    # 简单意图
    ("记一笔打车费50元", "expense_tracking"),
    ("北京天气怎么样", "information_query"),
    ("100美元换人民币", "currency_conversion"),
    
    # 中等复杂度
    ("我喜欢住汉庭酒店", "preference"),
    ("我之前去过哪里", "memory_query"),
    
    # 复杂意图
    ("帮我规划北京三日游", "itinerary_planning"),
    ("我下周要从上海去杭州出差，帮我安排一下", "event_collection"),
]
```

### 测试脚本

```python
#!/usr/bin/env python3
"""MiMo模型性能对比测试"""

import asyncio
import time
from openai import AsyncOpenAI

async def test_model(model_name: str, test_cases: list, api_key: str):
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.xiaomimimo.com/v1"
    )
    
    results = []
    for query, expected_intent in test_cases:
        start = time.time()
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": f"识别意图: {query}"}],
                max_tokens=100,
                temperature=0.1
            )
            elapsed = time.time() - start
            results.append({
                "query": query,
                "time": elapsed,
                "success": True
            })
        except Exception as e:
            results.append({
                "query": query,
                "time": None,
                "success": False,
                "error": str(e)
            })
    
    return results

async def main():
    api_key = "YOUR_API_KEY"
    models = ["mimo-v2.5-pro", "mimo-v2.5-turbo", "mimo-v2.5-lite"]
    
    test_cases = [
        ("记一笔打车费50元", "expense_tracking"),
        ("北京天气怎么样", "information_query"),
        ("100美元换人民币", "currency_conversion"),
    ]
    
    for model in models:
        print(f"\n=== Testing {model} ===")
        results = await test_model(model, test_cases, api_key)
        
        times = [r["time"] for r in results if r["success"]]
        if times:
            print(f"Average: {sum(times)/len(times):.2f}s")
            print(f"Min: {min(times):.2f}s")
            print(f"Max: {max(times):.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 推荐配置方案

### 方案1：保守方案（保持单一模型）

```env
# 保持现有配置，仅通过规则快速路径优化
ALIGO_MODEL_NAME=mimo-v2.5-pro
```

**优点**: 简单，无需额外配置
**缺点**: 简单任务响应仍然较慢

### 方案2：双模型方案（推荐）

```env
# 主模型
ALIGO_MODEL_NAME=mimo-v2.5-pro

# 意图识别专用（需要先测试确认模型可用）
ALIGO_INTENTION_MODEL=mimo-v2.5-turbo
```

**优点**: 简单任务响应快，复杂任务质量有保障
**缺点**: 需要管理两个模型配置

### 方案3：规则优先方案

```env
# 仅使用一个模型，但通过规则引擎跳过LLM
ALIGO_MODEL_NAME=mimo-v2.5-pro
```

配合 `FastRouter` 实现：
- 记账、天气、汇率 → 规则直接处理（0次LLM）
- 其他意图 → LLM识别

**优点**: 最简单，效果明显
**缺点**: 规则覆盖有限

---

## 下一步行动

1. **确认可用模型**: 调用 `GET /v1/models` 获取小米MiMo实际支持的模型列表
2. **性能测试**: 使用上述脚本测试不同模型的响应时间
3. **选择方案**: 根据测试结果选择最优配置
4. **实施优化**: 按照 `OPTIMIZATION_PLAN.md` 中的方案进行代码改造

---

## 参考链接

- [小米MiMo官网](https://xiaomimimo.com)
- [MiMo API文档](https://api.xiaomimimo.com/docs)
- [HuggingFace - XiaomiMiMo](https://huggingface.co/XiaomiMiMo)
- [OpenRouter模型列表](https://openrouter.ai/models) (可能包含MiMo)
