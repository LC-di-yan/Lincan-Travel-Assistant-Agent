# AgentScope 升级双跑对比报告（P8）

> 生成时间：2026-11-06 | 方式：`tools/as2_ab_probe.py` 在 1.0.16 与 2.0.11 两个解释器下各跑一次
> 环境：1.0.16 → `.venv-as1`（--system-site-packages + agentscope==1.0.16 + mcp==1.27.2）
> 2.0.11 → 主环境（agentscope==2.0.11 + mcp==2.3.0）

## 探针结果

| 探针 | 1.0.16 | 2.0.11 | 判定 |
|---|---|---|---|
| `agentscope.__version__` | 1.0.16 | 2.0.11 | — |
| 存在 `agentscope.init` | ✅ true | ❌ false | 已按计划改用 `setup_logger` |
| `as_compat` 识别的主版本 | 1 | 2 | ✅ 双版本自适应 |
| `as_messages()` 产物 | `dict` 列表 | `Msg` 列表 | ✅ 版本分支正确 |
| Msg JSON 往返 | ✅ | ✅ | ✅ 行为一致 |
| `msg_text` 取文本 | 纯文本 | 纯文本 | ✅ |
| SKILL.md 装载 | 无原生 loader（走自研 skill_loader） | `LocalSkillLoader` **13 个** | ✅ 2.x 原生可用 |
| Skill → Toolkit 工具 | 不适用（无 FunctionTool 契约） | **13 个** | ✅ P5 桥接生效 |
| RAG 40 题 Hit@1 / Hit@3 / Hit@4 / MRR | 0.575 / 0.900 / 0.975 / 0.744 | 同左，**逐位一致** | ✅ 零检索回归 |
| 树导航参与 / 平均耗时 | 38/40 · 20ms | 38/40 · 20ms | ✅ |
| 全量 pytest | 169 passed / 7 skipped | 175 passed / 7 skipped | ✅ 新增 6 项（结构化 2 + 工具桥 4） |

原始数据：`data/ab_1016.json`、`data/ab_2011.json`、`data/rag_1016.txt`、`data/rag_2011.txt`

## 回滚演练（实测）

```powershell
python -m venv .venv-as1 --system-site-packages
.venv-as1\Scripts\pip install agentscope==1.0.16 mcp==1.27.2
.venv-as1\Scripts\python tools/as2_ab_probe.py    # version=1.0.16，探针全过
```

**关键教训**：只降 `agentscope` 不降 `mcp` 会失败——2.0.11 把 mcp 抬到 2.x，而 1.0.16 依赖
`mcp.client.streamable_http.streamablehttp_client`（2.x 已改名）。因此回滚必须
`pip install -r data/baseline/pip-1.0.16.txt`（含 mcp==1.27.2），而不是单装 agentscope。

## 结论

- 两个版本在**业务语义层**（消息文本、检索指标）完全等价；
- 差异只存在于框架 API 形态（init/AgentBase/Msg 块/工具契约），且已被 `utils/as_compat.py` 吸收；
- 主环境已切 2.0.11 且全量绿；回滚路径实测可用。
