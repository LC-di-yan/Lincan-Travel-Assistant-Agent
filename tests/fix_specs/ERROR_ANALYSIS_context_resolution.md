# 错误分析：AI 为什么还是不能结合上下文

> **场景**：
> 1. 用户："明天从北京去上海出差3天" → AI 生成完整 3 天上海行程（含"汉庭酒店近外滩"）
> 2. 用户："请帮我查询具体的汉庭酒店房型和价格" → AI："请问您想查哪个城市的汉庭酒店？"
>
> 用户明明刚在上一轮提到上海、AI 上一轮还推荐了汉庭酒店，下一轮却被反问城市。这是典型的上下文丢失。

## 直接根因

`server/routes/chat.py:156` 在调用意图识别前先跑 `_fast_match(request.message)` 做快速路由，**而 `_fast_match` 是无上下文的纯函数**：

```python
# server/routes/chat.py:155-157
from agents.intention_agent import _fast_match
_is_fast = _fast_match(request.message) is not None
if not _is_fast and session.messages_since_summary >= 10:
    ...
```

这次只用于判断是否触发长期记忆总结。但**真正的意图识别**（`session.intention_agent.reply(context_messages)` 在 chat.py:206）虽然传了 `context_messages`，问题出在 `IntentionAgent.reply()` 内部对上下文的处理。

## 完整调用链分析

### 第 2 轮 "请帮我查询具体的汉庭酒店房型和价格"

```
chat.py:206  session.intention_agent.reply(context_messages)
  ↓
intention_agent.py:575  _fast_match(user_query, dialogue_history=_dialogue)
  ↓
_fast_match("请帮我查询具体的汉庭酒店房型和价格", [])
  ↓
命中 _HOTEL_PATTERNS 第3条：(帮我找|帮我查|搜索|推荐|看看).*?(酒店|民宿|...)
  ↓
提取城市：q 中无 _CITY_KEYWORDS 命中 → city = ""
  ↓
intention_agent.py:481  if not city and _has_history: return None
  ↓
_has_history = bool([]) = False  ← ★ 关键：_fast_match 收到的 dialogue_history 是空的
  ↓
city 为空但无历史 → 不 return None，继续走
  ↓
返回 hotel_search，key_entities={} （destination 为空）
```

然后这个 `fast` 结果直接被 `IntentionAgent.reply()` 返回，**LLM 路径完全没执行**（intention_agent.py:577-581）：

```python
# intention_agent.py:577-581
fast = _fast_match(user_query, dialogue_history=_dialogue)
if fast:
    return Msg(name=self.name, content=json.dumps(fast, ensure_ascii=False), role="assistant")
```

## 三个嵌套 Bug

### Bug A：`_fast_match` 拿到的对话历史为空

`intention_agent.py:562` 提取 `_dialogue`：

```python
# intention_agent.py:560-562
_dialogue = [h for h in self.conversation_history if not h.startswith("[系统记忆]")]
```

而 `self.conversation_history` 是在 `reply()` 入口处从传入的 `context_messages` 构建的（intention_agent.py:543-556）：

```python
# intention_agent.py:543-556
if isinstance(x, list):
    user_query = x[-1].content if x else ""
    self.conversation_history = []
    for msg in x[:-1]:
        if hasattr(msg, 'content') and hasattr(msg, 'role'):
            if msg.role == "system":
                summary = msg.content[:500] ...
                self.conversation_history.append(f"[系统记忆]\n{summary}")
            else:
                role_name = "用户" if msg.role == "user" else "助手"
                content = msg.content[:300] ...
                self.conversation_history.append(f"{role_name}: {content}")
```

这部分逻辑本身是对的——会把历史 user/assistant 消息加进 `self.conversation_history`。**问题在于 `chat.py:172-179` 构造的 `context_messages` 只含最近 3 轮**：

```python
# chat.py:172
recent_context = session.memory_manager.short_term.get_recent_context(n_turns=3)
```

但第 1 轮的行程规划回复非常长（3000+ 字的 3 天行程），`intention_agent.py:553` 把每条消息截断到 **300 字**：

```python
# intention_agent.py:553-555
content = msg.content[:300] if len(msg.content) > 300 else msg.content
if len(msg.content) > 300:
    content += "..."
```

第 1 轮 assistant 回复被截断后，"上海"两个字可能还在（出现在"北京到上海3日出差行程"标题里），但更关键的"汉庭酒店（近外滩）"这种细节被截掉了。**而且 fast route 命中后根本不走 LLM**，上下文完全没用上。

### Bug B：fast route 命中后无城市时未走 LLM 兜底

`intention_agent.py:481` 的逻辑：

```python
# intention_agent.py:475-482
if not city:
    for c in _CITY_KEYWORDS:
        if c in q:
            city = c
            break
# 有对话历史但没提取到城市 → 交给 LLM 用历史补全
if not city and _has_history:
    return None
```

这里 `_has_history` 来自 `_fast_match` 的 `dialogue_history` 参数。但**第 2 轮实际是有历史的**（第 1 轮的 user+assistant），只是 `_dialogue` 在 `IntentionAgent.reply()` 里被正确填充了。让我重新核对——

实际上 `_dialogue` 不为空（含"用户: 明天从北京去上海出差3天" 和 "助手: 北京到上海3日出差行程..."）。所以 `_has_history=True`，`if not city and _has_history: return None` 应该触发，走 LLM。

**但实测反问了城市**，说明 LLM 路径也没用上下文，或者 LLM 也失败了。看 LLM prompt（intention_agent.py:629-728）确实把 `context_str` 拼进去了：

```python
prompt = f"""你是意图识别专家。分析用户查询，输出JSON决策。
【当前时间】{current_time} {weekday}
【用户Query】{user_query}
【对话历史】{context_str}
...
"""
```

`context_str` 来自 `self.conversation_history`（含截断后的历史）。LLM 应该能从"用户: 明天从北京去上海出差3天"里看到"上海"。

**真正的问题**：LLM 识别出 `hotel_search` 意图后，按 prompt 指示（intention_agent.py:684-691）检查关键实体缺失：

```
【关键信息缺失处理】
- 当检测到差旅需求时，检查关键实体是否完整：origin、destination、start_date
- 优先级：destination > origin > start_date，至少需要 destination 才视为有效差旅需求
- 如果destination存在但origin缺失且无法从偏好推断，必须设置 needs_clarification=true
```

**这段 prompt 只对"差旅需求"做缺失检查**，对"酒店搜索"没有对应规则。LLM 看到"查汉庭酒店"但 query 里无城市，又没被指示从对话历史回填 destination，于是输出 `needs_clarification=true` + 反问城市。

### Bug C：assistant 回复摘要丢失关键实体

`chat.py:322-324` 把 orchestrator 结果转成"自然语言摘要"再存入记忆：

```python
# chat.py:322-324
from server.utils.assistant_summary import build_assistant_summary
assistant_summary = build_assistant_summary(result_data)
await session.memory_manager.add_message_async("assistant", assistant_summary)
```

如果 `build_assistant_summary` 没把"上海""汉庭酒店"这种关键实体保留进摘要，下一轮 `context_messages` 里就只剩模糊描述，LLM 即使读上下文也提取不到 destination。

## 根因总结表

| Bug | 位置 | 现象 | 根因 |
|-----|------|------|------|
| A | `intention_agent.py:577-581` | fast route 命中后跳过 LLM | `_fast_match` 命中 hotel_search 直接返回，不用上下文 |
| B | `intention_agent.py:481` | 无城市时仅在有历史才走 LLM | 第 2 轮实际有历史，但 LLM prompt 对酒店搜索无"从历史回填 destination"指示 |
| C | `intention_agent.py:684-691` | LLM 不回填酒店城市 | prompt 的缺失检查只针对差旅需求，酒店/餐厅/景点搜索无对应规则 |
| D | `intention_agent.py:553` | 历史消息截断 300 字 | 长行程回复被截断，关键实体可能丢失 |
| E | `chat.py:322-324` | assistant 摘要可能丢实体 | `build_assistant_summary` 实现未审计，需确认是否保留城市/酒店名 |

## 复现路径

```python
# 模拟第 2 轮
from agents.intention_agent import IntentionAgent, _fast_match

# 1. fast route 测试（无历史）
q = "请帮我查询具体的汉庭酒店房型和价格"
r = _fast_match(q, dialogue_history=[])
# 实际：命中 hotel_search，city=""
# 期望：return None（无城市走 LLM）

# 2. fast route 测试（有历史）
dialogue = [
    "用户: 明天从北京去上海出差3天",
    "助手: 北京到上海3日出差行程...汉庭酒店(近外滩)..."
]
r = _fast_match(q, dialogue_history=dialogue)
# 实际：if not city and _has_history: return None → 走 LLM
# 但 LLM prompt 不指示回填，仍可能反问

# 3. LLM 路径
# intention_agent.py:629-728 的 prompt 对酒店搜索无"从历史回填 destination"规则
```

## 修复方案

### 修复 1：fast route 无城市时强制走 LLM（无论是否有历史）

`intention_agent.py:475-482` 改为：

```python
# 无城市无法搜酒店 → 交给 LLM 推断（如"汉庭酒店"→从历史推断上海）
if not city:
    return None
```

同样改餐厅/景点分支（511-514、533-536）。**这一步我之前在修 CE-006 时已经做了**，但只对 `not city` 生效。问题在于第 2 轮的 `_fast_match` 调用——如果 LLM 路径仍不回填，反问依旧出现。

### 修复 2：LLM prompt 增加酒店/餐厅/景点搜索的上下文回填规则

`intention_agent.py:684-691` 的"关键信息缺失处理"章节扩展：

```
【关键信息缺失处理】
- 差旅需求：检查 origin/destination/start_date（原有规则）
- 酒店/餐厅/景点搜索：检查 destination
  - 如果 query 本身无城市，必须从【对话历史】最近一轮提取城市回填
  - 示例：历史有"明天从北京去上海出差"，用户追问"查汉庭酒店" → destination=上海
  - 仅当历史中也无法提取城市时，才设置 needs_clarification=true
- 非差旅/搜索场景（天气/汇率/翻译/知识库等）不需要此检查
```

### 修复 3：放宽历史消息截断

`intention_agent.py:553` 把 300 字提到 800 字或只截断 user 消息、保留 assistant 完整：

```python
# user 消息通常短，保留完整；assistant 摘要保留更长
if msg.role == "user":
    content = msg.content  # 不截断
else:
    content = msg.content[:800] if len(msg.content) > 800 else msg.content
    if len(msg.content) > 800:
        content += "..."
```

### 修复 4：审计 `build_assistant_summary`

确认 `server/utils/assistant_summary.py` 是否保留城市/酒店名等关键实体。若不保留，改进摘要生成逻辑或直接存原始 JSON 的关键字段。

### 修复 5（可选）：fast route 命中后也注入历史实体

`_fast_match` 命中 hotel_search 但 city 为空时，不直接 return None，而是从 `dialogue_history` 里提取最近城市回填：

```python
if not city and _has_history:
    # 从历史最近一轮提取城市
    for item in reversed(_dialogue):
        for c in _CITY_KEYWORDS:
            if c in item:
                city = c
                break
        if city:
            break
    if city:
        # 用回填的城市继续 fast route
        return {...}
    return None
```

这样 fast route 也能利用上下文，不用全交给 LLM。

## 验证用例

新增审计用例 `tests/logic_audit/cases/16_context_resolution.json`：

```json
[
  {
    "id": "CR-001",
    "category": "context_resolution",
    "query": "请帮我查询具体的汉庭酒店房型和价格",
    "dialogue": [
      "用户: 明天从北京去上海出差3天",
      "助手: 北京到上海3日出差行程...汉庭酒店(近外滩)..."
    ],
    "expected": {
      "agents": ["hotel_search"],
      "key_entities_destination": "上海",
      "needs_clarification": false
    },
    "note": "追问酒店时应从历史回填 destination=上海，不应反问城市"
  },
  {
    "id": "CR-002",
    "category": "context_resolution",
    "query": "帮我查一下汉庭的房型",
    "dialogue": [
      "用户: 帮我规划杭州2天旅游",
      "助手: 杭州2日行程...汉庭酒店..."
    ],
    "expected": {
      "agents": ["hotel_search"],
      "key_entities_destination": "杭州",
      "needs_clarification": false
    },
    "note": "历史含杭州，追问酒店应回填"
  }
]
```

这类用例需要 runner 支持 `dialogue` 字段透传给 `_fast_match` 与 LLM mock——当前 runner 只调 `_fast_match`，LLM 路径无法静态验证，需另建 LLM 行为测试。

## 优先级

| 修复 | 优先级 | 难度 | 风险 |
|------|--------|------|------|
| 修复 2（LLM prompt 回填规则） | P0 | 低 | 低 |
| 修复 5（fast route 历史回填） | P0 | 中 | 中（可能误回填） |
| 修复 3（放宽截断） | P1 | 低 | 低 |
| 修复 4（审计摘要） | P1 | 中 | 中 |
| 修复 1（已做） | — | — | — |

**最小修复**：先做修复 2 + 修复 5，覆盖 90% 的追问场景。

## 根本性反思

当前架构有两个结构性问题导致"上下文结合"不可靠：

1. **fast route 与 LLM 路径割裂**：fast route 是无状态的纯函数，命中即返回，完全不用上下文。任何含关键词但缺实体的追问都会被 fast route 吞掉。修复 5 能缓解，但本质上是"在无状态函数里硬塞上下文"，不优雅。

2. **LLM prompt 的缺失检查不通用**：只对差旅需求做 destination/origin 检查，其他意图（酒店/餐厅/景点）没有"从历史回填实体"的指示。LLM 默认行为是"缺信息就反问"，而不是"先查历史"。修复 2 能解决，但每加一类意图都要补规则，扩展性差。

长期改进方向：把"实体回填"做成独立的 post-processing 层——LLM 输出意图后，统一从 `context_messages` 里回填缺失的 origin/destination/date，再决定是否反问。这样 prompt 简化、行为一致。
