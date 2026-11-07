# 决策层影子回放分析与 assist 提升评估

> 日期：2026-11-07 ｜ 后端：`jev`（TypeSafe `/v1/systemone`）｜ 模式：`shadow`
> 结论：**暂不切 assist**——实测收益为 0、成本约 +797ms/请求；已改为直接修掉正则缺陷。

## 1. 样本采集

`tools/collect_shadow_samples.py`：24 条真实风格查询走**完整生产链路**
（`IntentionAgent.reply()`，快路由与 LLM 路径都会落 outcome），不是直接调 `engine.route`。

- 24/24 成功，耗时 97s
- 产出成对记录：`kind=decision`（模型判断）+ `kind=outcome`（最终路径）

## 2. 回放结果（`python tools/replay_shadow.py --date 20261107`）

| 指标 | 值 |
|---|---|
| 成对记录 | 24（24 条有结局） |
| **意图一致率** | **21/24 = 87.5%** |
| 冲突条数 | 0 |
| 决策耗时 | 中位 797ms · P90 2000ms |
| 最终路径分布 | fast 13 · llm 11 |

### 三条不一致

| 查询 | 决策层 | 现有链路 | 谁更准 |
|---|---|---|---|
| 今天天气真不错啊 | chitchat (0.95) | fast → information_query | **决策层**（这是感叹句，不该查天气） |
| 去泰国需要签证吗 | rag_knowledge (0.86) | llm → visa_info | 链路（粒度更细；签证有专用 skill） |
| 日本签证有效期是多久 | rag_knowledge (0.90) | llm → visa_info | 链路（同上） |

## 3. assist 提升评估（`tools/simulate_assist_veto.py`）

用真实样本离线重放 `_should_veto`：

```
RISKY_AGENTS = ['hotel_search', 'memory_query', 'restaurant_search', 'scenic_search']
fast 路径样本 = 15
assist 会否决 = 0  (0.0% of fast)
```

**为什么是 0**：assist 只在正则命中 `RISKY_AGENTS` 时才可能否决；唯一「决策层更准」的
天气误判走的是 `information_query`，不在该集合内，assist 根本不会介入。
另两条不一致走的是 LLM 路径，而 assist 在 `fast is None` 时直接返回 off，也不会介入。

**成本**：shadow 是 `asyncio.create_task` 异步旁路（fast 路径保持 0ms）；
assist 是 `await engine.route(...)` **同步阻塞**，会给每个正则命中的请求加上决策耗时
（本批中位 797ms）。

| 方案 | 收益 | 成本 |
|---|---|---|
| 保持 shadow | 持续积累样本，零延迟 | 无 |
| 切 assist | 本批样本 **0 次否决 → 0 收益** | fast 路径 +797ms 中位 |

→ **判定：保持 shadow。** 若将来要切，前置条件应是「样本里出现 ≥1 次正确否决」，
而不是单看一致率数字。

## 4. 改为直接修根因（已落地）

影子数据的真正价值是暴露了正则缺陷，直接修比切 assist 更划算：

- `agents/intention_agent.py` 新增 `_WEATHER_COMMENT_RE` / `_WEATHER_QUERY_SIGNAL_RE`：
  命中天气评价词（真不错/太热/很差…）且**无任何查询信号**（怎么样/查/预报/多少度/？…）
  → 放弃快路由，交给 LLM 判闲聊。
- 回归测试 `tests/test_weather_fast_route.py` 6 passed（评价句跳过、正常查询不受影响、
  「评价+提问」混合句不误杀、非天气查询不受影响）。
- 端到端实测：
  - `今天天气真不错啊` → `intents=[] agents=[]`（修复前是 information_query）
  - `杭州下周天气怎么样` → `intents=['information_query']`（不变）

## 5. 顺带解锁的评测

`tests/test_decision_eval.py` 此前因缺 `NEOHOUSE_API_KEY` 被跳过；现在有真实 key，
以 `ALIGO_DECISION_EVAL=1 ALIGO_DECISION_BACKEND=jev` 跑通：**1 passed**（24 条金标准门禁）。

```powershell
$env:NEOHOUSE_API_KEY="<sk_tr_...>"; $env:ALIGO_DECISION_EVAL="1"; $env:ALIGO_DECISION_BACKEND="jev"
python -m pytest tests/test_decision_eval.py -q
```

## 6. 复跑方式

```powershell
python tools/collect_shadow_samples.py          # 采集（走完整链路，约 100s）
python tools/replay_shadow.py --date YYYYMMDD   # 一致率报表
python tools/simulate_assist_veto.py            # assist 否决模拟（决定是否值得切）
```
