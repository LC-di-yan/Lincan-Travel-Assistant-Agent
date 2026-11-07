# 提交门禁与 CI

> 2026-11-07 建立。此前两个门禁脚本（`check_as2_gate.py` / `scan_secrets.py`）虽已存在，
> 但**没有任何自动执行点**——无 CI、无 pre-commit、无 git hook。
> 11-06 那次 `git add -A` 把含明文 key 的调试文件提交并推送（`7f10cbf:data/cv.txt`），
> 正是因为提交路径上没人拦。本文档所述机制就是补这个缺口。

## 三层防护

| 层 | 触发时机 | 跑什么 | 需要密钥 |
|---|---|---|---|
| 本地 pre-commit | 每次 `git commit` | 密钥扫描（**仅暂存内容**）+ AgentScope 1.x 写法门禁 | 否 |
| CI `guards` job（待激活） | push / PR 到 main | 同上（全量已跟踪文件） | 否 |
| CI `offline-tests` job（待激活） | push / PR 到 main | 离线用例 + RAG 40 题评测 | 否 |

> CI 工作流因凭据缺 `workflow` scope 无法推送，内容暂存 `docs/ci-workflow.yml`，
> 激活步骤见下文。**本地钩子不受影响，已生效。**

需要真实 LLM / 服务 / 音频 mock / 决策 key 的用例不在 CI 跑，完整跑法见
[零跳过指南](testing-full-suite.md)（本地实测 203 passed / 0 skipped）。

## 安装本地钩子

`.git/hooks` 不进版本库，**每个克隆各装一次**：

```powershell
python tools/install_hooks.py          # 安装
python tools/install_hooks.py --check  # 检查（已装 exit 0）
python tools/install_hooks.py --remove # 卸载
```

耗时约 1 秒。紧急绕过用 `git commit --no-verify`（不建议）。

## 密钥扫描器（`tools/scan_secrets.py`）

重写要点（旧版无法当门禁）：

| 问题 | 旧版 | 现在 |
|---|---|---|
| 虚拟环境误报 | 只排 `.venv`，漏 `.venv-as1/as2` → 上千条 `password=***` 命中 | 正则排除任何 `.venv*` / `venv*` / 构建产物 |
| 扫描范围 | 整个工作树（含未跟踪调试垃圾） | **默认只扫 git 已跟踪文件**（密钥只有进版本库才算泄漏）；`--all` 扫工作树并尊重 gitignore；`--staged` 供钩子用 |
| 退出码 | 任何命中即 1，含误报 → 无法当门禁 | **棘轮基线**：只有新增命中才 1；`--update` / `--prune` 与 as2 门禁同约定 |
| 测试假 key | 被当成泄漏 | `tests/` 下含 test/dummy/fake/abcd 等特征的串自动忽略；同样串出现在生产代码仍报 |
| 检出类型 | 无 `sk_tr_`（正是泄漏那种） | 新增 TypeSafe `sk_tr_`、AWS `AKIA`、PEM 私钥块 |
| Windows | `subprocess(text=True)` 用 GBK 解 git 输出 → 中文文件名崩 | 显式 UTF-8 + `core.quotepath=false` |

**从不打印明文**，只输出 `路径:行号 [类型] 前6…后4`。

### 刻意构造的样本：用 `# nosec` 行内豁免

测试里有时需要「长得像真 key」的样本来验证检出能力，这类会被自己的扫描器拦住
（本工具上线时就拦下了作者本人的提交）。用 bandit 惯例的行内豁免，**并写明理由**：

```python
p = _write(tmp, "req.md", "Authorization: Bearer A1b2...")  # nosec 合成样本，验证 bearer 检出
```

Markdown 用 `<!-- nosec 理由 -->`。豁免与代码同处一行，评审时直接可见，
比登记到基线文件更好审计。**没有该标记则照常报出**（`tests/test_scan_secrets.py`
里有正反两向断言）。

### 检出能力已验证

`tests/test_scan_secrets.py` 12 项：OpenAI / TypeSafe / GitHub / AWS / PEM 私钥 / Bearer
六类正向检出，占位符与测试假 key 抑制，venv 目录排除，脱敏不含完整明文，
基线键与行号无关。

端到端实测：
- 注入合成 `sk_tr_` 到已跟踪文件 → `exit 1`，输出 `sk_tr_…o8N7`
- 移除后 → `exit 0`
- **真实 `git commit` 被钩子拦下**，HEAD 未变，提示可操作

## AgentScope 1.x 写法门禁

见 `tools/check_as2_gate.py` 与[升级计划](agentscope-2-upgrade-dev-plan.md)。
8 类禁止写法，棘轮白名单当前为空（0 残留）。

## CI 无需任何 secret（工作流待激活）

工作流内容已备好在 **`docs/ci-workflow.yml`**，刻意**不创建 `.env`**，
以验证「新克隆 / 无密钥」也能跑绿。本地用同样条件实测：**199 passed / 3 skipped / 9.8s**。

### 为什么放在 docs/ 而不是 .github/workflows/

推送时被 GitHub 拒绝：

```
! [remote rejected] main -> main (refusing to allow an OAuth App to create or update
  workflow `.github/workflows/ci.yml` without `workflow` scope)
```

当前 git 凭据是 OAuth App 且缺 `workflow` scope，**无法由本工具推送工作流文件**。
其余改动不受影响，已正常推送。

### 激活方式（任选其一，都只需一次）

1. **GitHub 网页**：仓库 → Add file → Create new file，路径填 `.github/workflows/ci.yml`，
   粘贴 `docs/ci-workflow.yml` 的内容，提交。
2. **带 workflow scope 的 PAT**：换成有 `workflow` 权限的 Personal Access Token 后，
   本地 `copy docs\ci-workflow.yml .github\workflows\ci.yml` 再提交推送。
3. **GitHub CLI**：`gh auth refresh -s workflow` 后同上。

激活后每次 push / PR 到 main 会自动跑 guards 与 offline-tests 两个 job。
**在激活之前，本地 pre-commit 钩子已经生效**，密钥与 1.x 写法都拦得住。

为此给 `tests/test_session_reuse.py` 加了跳过守卫——`SessionManager()` 构造即创建
OpenAI 客户端，缺 `ALIGO_API_KEY` 会抛 `OpenAIError`；无配置环境应跳过而非失败。
