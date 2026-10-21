# 错误分析：上下文回填为何还是失败

> **场景复现**（20:11 用户实测）：
> 1. 用户："明天从北京去上海出差3天" → AI 生成上海3日行程（含"上海酒店"卡片）
> 2. 用户："附近有哪些酒店和餐厅" → AI 反问"请问您当前所在城市是哪里？"
>
> 已做过 5 轮修复（fast route 历史回填 + LLM prompt 扩展 + assistant 摘要实体保留），
> 静态审计 84 用例 0 bug，端到端模拟也通过。但真实运行仍失败。

## 直接观察

- 第 2 轮 AI 输出「识别意图 hotel_search 95% / restaurant_search 95%」「关键信息：查询缺少城市，需要反问用户位置」——这是 **LLM 路径**的输出格式，fast route 没命中。
- 后端日志（uvicorn stdout）没有任何 chat 请求记录，连 access log 都没有。

## 根因链（共 4 个 bug，按严重度排序）

### Bug 1（P0，根因）：`_city_from_history` 被"南京路"误导，回填了错误城市

`agents/intention_agent.py:295-329` 的回填逻辑：

```python
def _city_from_history(dialogue_history: list) -> str:
    def _last_match(text: str, names) -> str:
        last_city = ""
        last_pos = -1
        for c in names:
            pos = text.rfind(c)
            if pos > last_pos:
                last_pos = pos
                last_city = c
        return last_city

    for item in reversed(dialogue_history):
        city = _last_match(item, _CITY_KEYWORDS)
        if city:
            return city
```

实测：

```python
dialogue = [
    '用户: 明天从北京去上海出差3天',
    '助手: 已规划3天行程：上海出差3日行程，目的地：上海，关键地点：虹桥、外滩、豫园、南京路，交通：高铁。'
]
# 期望：返回"上海"
# 实际：返回"南京"  ← 因为 assistant 摘要里有"南京路"
```

**为什么**：`_last_match` 在每条历史里用 `rfind` 找最后出现的城市名。assistant 摘要很长（150+ 字），"南京路"出现在末尾，`rfind("南京")` 返回的位置 > `rfind("上海")`。反向扫描时先扫 assistant（最后一条），命中"南京"直接返回。

**修复方案**：`_city_from_history` 改为**优先匹配 `目的地：X` 这种结构化实体**，找不到再退回 rfind：

```python
def _city_from_history(dialogue_history: list) -> str:
    if not dialogue_history:
        return ""
    
    import re
    # 优先：从 assistant 摘要的"目的地：X"结构提取
    for item in reversed(dialogue_history):
        m = re.search(r'目的地[：:]\s*([一-龥]{2,6})', item)
        if m:
            city = m.group(1).strip()
            # 校验是已知城市
            if city in _CITY_KEYWORDS or city in _EXTENDED_GEO_NAMES:
                return city
    
    # 次优：从 user 消息的"去X/到X/往X"模式提取
    for item in reversed(dialogue_history):
        if item.startswith("用户:"):
            m = re.search(r'(?:去|到|往|前往)\s*([一-龥]{2,4})', item)
            if m:
                city = m.group(1).strip()
                if city in _CITY_KEYWORDS:
                    return city
    
    # 兜底：rfind（可能被商圈名污染，需排除）
    _GEO_NOISE = {"南京路", "人民广场", "静安寺", "陆家嘴", "外滩", "豫园", "虹桥", "北京路"}
    def _last_match(text: str, names) -> str:
        last_city = ""
        last_pos = -1
        for c in names:
            # 排除"南京路"这种被污染的子串
            for noise in _GEO_NOISE:
                if noise.startswith(c):
                    # 检查 c 后面是不是接"路/广场/寺"等
                    idx = text.rfind(c)
                    while idx != -1:
                        suffix = text[idx + len(c): idx + len(c) + 1]
                        if suffix in "路广场寺场站":
                            idx = text.rfind(c, 0, idx)
                            continue
                        if idx > last_pos:
                            last_pos = idx
                            last_city = c
                        break
            else:
                pos = text.rfind(c)
                if pos > last_pos:
                    last_pos = pos
                    last_city = c
        return last_city
    
    for item in reversed(dialogue_history):
        city = _last_match(item, _CITY_KEYWORDS)
        if city:
            return city
    return ""
```

**验证**：修复后，"目的地：上海"会被结构化提取，不会误返回"南京"。

### Bug 2（P0，加重 Bug 1）：fast route 回填错误城市后仍命中，导致 LLM 没机会纠错

`agents/intention_agent.py:536-540`：

```python
# 无城市时从对话历史回填（追问场景：上一轮已提到城市）
if not city and dialogue_history:
    city = _city_from_history(dialogue_history)
# 仍无城市 → 交给 LLM 推断（如"虹桥火车站附近"→上海）
if not city:
    return None
```

**问题**：`_city_from_history` 返回了错误城市"南京"（非空），所以 `if not city: return None` 不触发，fast route 直接返回 `destination=南京`。**LLM 路径根本没执行**。

**实测现象**：用户看到的反问"请问您当前所在城市是哪里？"——这其实是 LLM 路径的输出。说明 fast route **没有命中**，走了 LLM。为什么？

**真正的 fast route 没命中的原因**（重新分析）：

`_fast_match("附近有哪些酒店和餐厅", dialogue)` 测试结果：
- `_HOTEL_PATTERNS[0]` `(.{2,6})[的有]?(?:哪些|什么|哪家|哪[些家]|有没有|有没).*?(?:酒店|民宿|...)` → 匹配，group(1) = "附近"
- "附近" 不在 `_CITY_KEYWORDS`，city = ""
- 走回填 → `_city_from_history` 返回 "南京"（错误）
- city 非空 → 返回 hotel_search + destination=南京

但用户看到的是 LLM 反问，说明实际 fast route **返回了 None**。这只可能是：
- a) `dialogue_history` 为空（短期记忆丢失，见 Bug 3）
- b) `_city_from_history` 返回了空（不可能，对话里有"上海"）

**结论**：用户那次请求，`dialogue_history` 是空的。短期记忆丢了。

### Bug 3（P0，真正的根因）：短期记忆丢失，第 2 轮 `_dialogue` 为空

`server/routes/chat.py:172`：

```python
recent_context = session.memory_manager.short_term.get_recent_context(n_turns=3)
```

`short_term` 是 `ShortTermMemory` 实例，**纯内存**（`context/short_term_memory.py:28` `self.messages: List[Dict[str, Any]] = []`）。无持久化。

`session` 来自 `session_manager.get_or_create(user_id, session_id)`，session 缓存在 `session_manager._sessions` dict 里。

**短期记忆丢失的可能场景**：

1. **后端重启**：进程重启后 `session_manager._sessions` 清空，所有短期记忆丢失。用户第 1 轮在旧进程，第 2 轮打到新进程 → 记忆空。
   - 本次 20:11 测试时，后端是 20:04 启动的，用户对话是 20:11，**应该是同一进程**。
   - 但 Windows netstat 显示 `0.0.0.0:8010` 和 `127.0.0.1:8010` 两个监听，可能前端代理到了错误进程。

2. **session_id 切换**：前端 Zustand store 在页面刷新时重置 `sessionId: null`，下次发消息会调 `/api/session/new` 创建**新 session**，短期记忆从 0 开始。
   - 用户可能在两条消息之间刷新了页面（或 Vite HMR 触发了 store 重置）。
   - 前端 `web/src/store/chatStore.ts:37` `sessionId: null` 是初始值，没有从 localStorage 恢复。

3. **LRU 淘汰**：`session_manager._evict_if_needed` 在 session 数量超过 `MAX_SESSIONS=50` 时淘汰最老的。单用户测试不会触发。

**修复方案**：
- A. 前端把 sessionId 持久化到 localStorage，刷新后恢复：
  ```typescript
  // chatStore.ts
  sessionId: localStorage.getItem('aligo_session_id') || null,
  setSessionId: (id) => {
    localStorage.setItem('aligo_session_id', id)
    set({ sessionId: id })
  },
  ```
- B. 后端短期记忆持久化到 `data/memory/{user_id}.json` 的 `chat_history` 字段（已存在），启动时加载。这是结构性改造，工作量大。

### Bug 4（P1，日志不可观测）：uvicorn stdout 被吞，debug print 不输出

本次诊断中，加了 `print(..., flush=True)` 和 `logger.warning(...)` 到 chat.py，但日志文件里**完全没有 chat 请求的任何记录**——连 uvicorn 自带的 access log（`INFO: 127.0.0.1:... - "POST /api/chat HTTP/1.1" 200`）都没有。

**可能原因**：
- Windows + uvicorn 子进程 + Claude Code 的后台任务管道，stdout 缓冲未刷新
- 或 uvicorn `--log-level info` 没生效，access log 被禁用

**修复方案**：
- 后端启动时加 `--access-log` 强制开启
- 关键诊断用 `logging.FileHandler` 写到独立文件，不依赖 stdout

## 修复优先级

| Bug | 优先级 | 难度 | 影响 |
|-----|--------|------|------|
| 1 | P0 | 中 | 回填错误城市，即使有记忆也错（"南京路"→南京） |
| 3 | P0 | 低 | 短期记忆丢失，回填无对象 |
| 2 | — | — | Bug 1 修复后自动消失（回填正确城市就命中 fast route） |
| 4 | P1 | 低 | 诊断困难，不影响功能 |

## 最小修复路径

1. **修 Bug 1**：改 `_city_from_history` 优先结构化提取「目的地：X」，避免被"南京路"污染
2. **修 Bug 3-A**：前端 sessionId 持久化到 localStorage
3. **重新测试**：连续两条消息不刷新页面，验证回填正确

## 静态审计的盲区

`tests/logic_audit/cases/16_context_resolution.json` 的 5 个用例里，assistant 摘要都没包含"南京路"这种商圈名，所以没暴露 Bug 1。需要补一个用例：

```json
{
  "id": "CR-006",
  "category": "context_resolution",
  "query": "附近有哪些酒店和餐厅",
  "dialogue": [
    "用户: 明天从北京去上海出差3天",
    "助手: 已规划3天行程：上海出差3日行程，目的地：上海，关键地点：虹桥、外滩、豫园、南京路，交通：高铁。"
  ],
  "expected": {
    "agents": ["hotel_search", "restaurant_search"],
    "key_entities_destination": "上海",
    "needs_clarification_not_true": true
  },
  "note": "assistant 摘要含'南京路'，不应被误回填为南京"
}
```

## 反思

5 轮修复都通过了静态审计和模拟测试，但真实运行还是失败——因为：

1. **静态审计的用例太干净**：assistant 摘要都是手工编的理想格式，没覆盖真实 LLM 生成的噪声（"南京路"等商圈名）。
2. **端到端模拟测试用 mock 摘要**：没跑真实 LLM 生成的摘要，漏掉了 Bug 1。
3. **没观测生产日志**：Bug 3（短期记忆丢失）在静态审计中无法暴露，需要真实请求日志。修 Bug 4 才能发现 Bug 3。

**教训**：上下文相关 bug 不能只靠静态审计，必须用真实 LLM 生成的对话历史做端到端测试，且日志必须可观测。
