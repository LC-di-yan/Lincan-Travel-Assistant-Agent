# AgentScope 2.0.11 升级交付说明（README 摘要）

> 本文档是升级工程的**入口索引**；细节见下述各文档。
> 一句话：**agentscope 1.0.16 → 2.0.11（断裂式大版本）已完成并全量验收，183 passed / 0 failed。**

## 交付范围一览

| 计划阶段 | 状态 | 交付物 |
|---|---|---|
| P0 基线与门禁 | ✅ | `tools/check_as2_gate.py`（8 类 1.x 写法静态棘轮门禁）、`tests/test_as2_gate.py` |
| P1 协议层 | ✅ | `utils/as_compat.py`（1.x/2.x 双版本自适应：mk_msg / msg_text / msg_json / as_messages / chat_text / build_chat_model / build_tool_schema / extract_tool_call_json / setup） |
| P2 消息通道收口 | ✅ | 78 处 `Msg(`、39 处 `json.loads(.content)`、14 处 `str(content)`、3 处切片全收口；门禁 0 残留 |
| P3 模型层 | ✅ | 14 处 `OpenAIChatModel` 构造收敛到 `build_chat_model`；18 处 dict 入参改 `as_messages` |
| P4 基类 | ✅ | `agents/base.py::SkillAgentBase`（取代已删除的 `AgentBase`）；`agents/__init__.py` PEP 562 懒加载 |
| P5 Skill 桥接 | ✅（加法式） | `agents/skill_toolkit.py`：13 个 SKILL.md 原生装载 + 13 个工具注册；**agent.py 零改动**（typed handler 按决策不做） |
| P6a 结构化输出 | ✅ | 意图识别走「强制单工具调用 + JSON schema」（`ALIGO_INTENT_STRUCTURED` 默认开，自动回退文本解析） |
| P6b Pipeline/SOP | ⛔ 不适用 | 需 2.x `Agent` 运行时；本项目编排为自研确定性调度（见升级计划 §11） |
| P7 决策层 | ✅ | `utils/decision_jev.py`：TypeSafe/Jev 后端，24 条金标准与自研后端判定等价且快 38%；本地已启用 `shadow + jev`（启用 jev 需 `pip install typesafe-sdk==0.7.5`，缺失则安全降级） |
| P7 SSE/权限/AskUser | ⛔ 不适用 | 同 P6b（依赖 Agent ReAct 循环） |
| P8 灰度双跑 | ✅ | `tools/as2_ab_probe.py` + `docs/as2-ab-report.md`；1.0.16 回滚演练实测通过 |

## 双版本验收矩阵

| 环境 | 结果 |
|---|---|
| 1.0.16（收口后） | 169 passed / 7 skipped / 0 failed |
| 2.0.11 + glm-5.3-flash（离线默认） | 196 passed / 7 skipped / 0 failed |
| **2.0.11 + 全前置条件齐备（最终）** | **203 passed / 0 skipped / 0 failed** |
| RAG 40 题检索指标（两版本） | **逐位一致**（Hit@1 0.575 · Hit@3 0.900 · Hit@4 0.975 · MRR 0.744） |
| 决策层 24 条金标准（custom vs jev） | 判定**逐条等价**；jev 中位 375ms（-38%） |

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/agentscope-2-upgrade-dev-plan.md` | 完整开发计划：API 速查 / 冲击面 / P0-P8 / 风险册 / 适用性结论 |
| `docs/agentscope-2-baseline.md` | 验收基线 + 全部线上实测记录（含踩坑） |
| `docs/as2-ab-report.md` | 1.0.16 vs 2.0.11 双跑对比 + 回滚演练 |
| `docs/decision-layer-dev-plan.md` | 决策层原始设计（前序工程） |

## 关键踩坑实录（一句话版，详见 baseline 文档）

1. 2.x 删除 `AgentBase` 与 `agentscope.init`；`Msg.content` 变块列表（39 处 `json.loads` 是静默失效高危点）。
2. 1.x `ChatResponse.__getattr__` 抛 **KeyError** 而非 AttributeError，`getattr(x, name, default)` 兜不住。
3. 2.x `ThinkingBlock` 没有 `.text`；块识别要按 `type` 属性，不能只认 `.text`。
4. TypeSafe SDK 自拼 `/v1/systemone`，base_url 惯例带 `/v1` 会双拼；SDK 默认 zstd 压缩大 body，tokenrhythm 网关回 400——必须 `_config.compression = None`（传 `False` 会踩 SDK 的 `is not None` 判断 bug）。
5. glm/compatible-mode 端点支持全部三种 `tool_choice` 模式但**不支持 `response_format`**（400）。
6. 回滚必须按 `pip install -r data/baseline/pip-1.0.16.txt`（含 `mcp==1.27.2`），单降 agentscope 会因 mcp 2.x 改名而 ImportError。

## 回滚

```powershell
pip install -r data/baseline/pip-1.0.16.txt   # agentscope==1.0.16 + mcp==1.27.2 一起降
git revert 70a9fb8..7f10cbf                    # 或直接回退到升级前提交 0424273
```

## 尚未闭环的事项（需使用者决定或提供条件）

| # | 事项 | 现状 | 需要什么 |
|---|---|---|---|
| 1 | 决策层 `shadow` → `assist` 提升 | ✅ **已评估：判定暂不切**。24 条真实样本一致率 87.5%，但 assist 否决模拟为 **0 次**（RISKY_AGENTS 不覆盖那唯一误判），切过去零收益且 fast 路径 +797ms。已改为直接修正天气正则缺陷。详见 [影子分析](decision-shadow-analysis.md) | 保持 shadow 继续积累；将来前置条件是「样本中出现 ≥1 次正确否决」，而非只看一致率 |
| 2 | `tests/test_cli_qa.py` 渲染入口失效 | ✅ **已修**（方案 A）：`cli.py` 补回 `_display_results`，遍历聚合 `results[]` 按 priority 排序并委托现有 `_display_single_agent_result`，与流式路径共用渲染器。7 项契约测试 + 真实 `capture_display_results()` 验证通过 | — |
| 3 | 高德 POI 路径未验证 | `AMAP_API_KEY` 未配置，`test_hotel_search.py` 自带守卫直接退出 | 配置 `AMAP_API_KEY` 后重跑该脚本 |
| 4 | skipped 用例 | ✅ **全部解锁并跑通**：构建 `web/dist` + 启动服务 + 音频 mock + 决策 key → **203 passed / 0 skipped**。复跑步骤见 [零跳过指南](testing-full-suite.md) | — |
| 5 | **TokenRhythm key 必须轮换** | ⚠️ **更正此前结论**：该 key 确实进过 git 历史并已推送 —— `7f10cbf:data/cv.txt` 含明文（由 `git add -A` 误纳入），`c340530` 才删除；另 `experiments/check_history_secrets.py` 曾在 HEAD 硬编码该 key（已删）。当前工作树/HEAD 已无残留，但**历史仍可检出** | **立即在 TokenRhythm 控制台轮换**（已推送的密钥不能只靠删文件）。如需彻底清除历史，见下方「历史清除」 |

## 安全事件更正与处置（2026-11-07）

**此前交付说明里「未进入 git 历史」的判断是错的**，特此更正。复核方式与结论：

| 检查 | 命令 | 结果 |
|---|---|---|
| 历史是否含 key | `git show 7f10cbf:data/cv.txt` | **含明文 key**（该提交已推送到 origin/main） |
| 何时移除 | `git log --all -- data/cv.txt` | `7f10cbf` 引入 → `c340530` 删除 |
| HEAD 是否残留 | `git grep -l '<key-prefix>' HEAD` | 曾在 `experiments/check_history_secrets.py`（扫描脚本硬编码了 key），**已删除** |
| 当前工作树 | `git grep -l '<key-prefix>'` | 无残留 |

> 踩坑教训：`git log -S <字符串>` 会把**删除**该字符串的提交也算命中，
> 只看「有没有命中」会误判；必须用 `git show <commit>:<path>` 直接验blob内容，
> 并区分 diff 里的 `+` / `-`。

### 已处置

- 删除硬编码 key 的扫描脚本；取消跟踪 `data/` 根目录 48 个探针日志
- `.gitignore` 收紧为 `data/*.txt` / `data/*.log`（不影响 `data/baseline/` 回滚基线）
- 全仓复扫：工作树与 HEAD 均无 key

### 仍需使用者执行

1. **轮换 TokenRhythm key**（必须）：密钥已推送到远端，删文件不等于失效。
2. **历史清除**（可选，破坏性）：
   ```bash
   pip install git-filter-repo
   git filter-repo --path data/cv.txt --invert-paths
   git filter-repo --path experiments/check_history_secrets.py --invert-paths
   git push --force-with-lease origin main
   ```
   代价：重写全部提交 hash，协作者需重新 clone；**且仍不能替代轮换**。
   本轮未执行此操作（需明确授权）。