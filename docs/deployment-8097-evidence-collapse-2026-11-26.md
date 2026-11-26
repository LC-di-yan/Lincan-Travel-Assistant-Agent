# 8097 发布：方案优先，证据收进一条横条（2026-11-26）

- 发布：`release-20261126-144626-evidence-collapse`；回退：`release-20261126-140049-liquid-glass`。
- 公网入口：`https://120.24.251.119:8097/`；发布记录 `/opt/aligo-travel/.deploy/20261126-144626-evidence-collapse/`。
- 前端-only：70 个构建产物，新入口 `index-D_AhYIF0.js` / `index-DIaN6WBM.css`。

## 背景

一条「明天去上海出差 3 天，预算 2000，帮我规划」会走证据工作流：去程车次、返程车次、住宿候选、目的地天气（有会场时再加通勤），最后出方案。每条工具结果都是一条 `AgentResult`，而前端 `ResultDashboard` 逐条渲染成完整卡片，于是方案卡 + 4 张证据卡堆成一屏——但方案卡里已经包含去程、住宿与费用。

## 改动

- `ResultDashboard`：检测到 `trip-plan` 时把它排到第一位；其余结果收进一个原生 `<details>` 横条，标题「本轮核验的证据」，摘要按卡片类型归并（如 `住宿 · 天气 / 信息 · 车次 ×2`），右侧显示项数，展开后仍是原来的完整卡片。
- 只有一张证据卡、或本轮没有方案卡时，保持原有逐条渲染。
- 不改接口、不改后端调度，证据仍然全部在 DOM 里，只是默认收起。

## 验证

- 本机：`tsc -b`、`eslint src`、`vite build` 通过。
- 本机端到端（真实后端，两轮：规划 → 回答「1」补人数）：`.proposal-shell` 在顶部；`details` 默认收起，摘要 `本轮核验的证据 | 失败项 ×2 · 车次 ×2 | 4 项`；展开后结果区从 499px 变 1757px，说明默认收起省掉约 1250px；零控制台报错。
- 服务器：stage 70 个文件哈希 + 入口资产检查通过；switch 健康门禁 `status=ok`、决策层 `primary/jev`；公网入口哈希与本地 byte 一致；`/api/health` 200。
- 公网浏览器：首页 4 个玻璃示例、零控制台错误、零失败请求。

## 回滚

```bash
ln -s /opt/aligo-travel/releases/release-20261126-140049-liquid-glass /opt/aligo-travel/.current-rollback
mv -Tf /opt/aligo-travel/.current-rollback /opt/aligo-travel/current
systemctl restart aligo-travel.service
```

## 说明

- 本次只改呈现顺序与可见性，没有减少工具调用；若要把往返车次/天气的调用本身降下来，需要改 `agents/trip_workflow.py` 的节点图，属于另一件事。
- 本地这轮酒店与天气节点失败（摘要因此显示「失败项 ×2」），与本次改动无关；全成功时应显示 `住宿 · 天气 / 信息 · 车次 ×2`。
