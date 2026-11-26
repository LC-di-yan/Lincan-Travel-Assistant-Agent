# 8097 发布：长按 1.5 秒删除 + 撤销（2026-11-26）

- 发布：`release-20261126-175257-delete-undo`；回退：`release-20261126-144626-evidence-collapse`。
- 公网入口：`https://120.24.251.119:8097/`；发布记录 `/opt/aligo-travel/.deploy/20261126-175257-delete-undo/`。
- 前端-only：70 个构建产物，新入口 `index-DUqtggE5.js` / `index-CzXrWzYX.css`。

## 改动

- 默认态：进度环的轨道与进度（圆头线帽在零长度时仍会画出一个小点）都改为 `opacity: 0`，卡片左上角不再有红点。
- 长按时长 2000ms → 1500ms；按住期间只显示 3px 进度环，卡片保持原配色，提前松手 / 移出 / pointercancel 立即取消并隐藏。
- 满 1.5 秒：卡片整体换成 `#d32f2f` 红底，居中显示「✓ 已删除」，并在卡片下方浮出胶囊状「撤销」按钮（`z-index: 6`，可点击）。
- 红色状态与「撤销」停留 800ms：无人点击则整行（卡片 + 撤销）`opacity` 在 240ms 内渐隐到 0，渐隐结束后才调用删除接口并从列表移除；点击「撤销」则清掉两个定时器、恢复原卡片，不发送任何删除请求。
- 键盘：Space/Enter 长按、Escape 取消；红色态按 Escape 等同撤销。
- 定时器（确认计时、渐隐计时）在取消、撤销、卸载时统一清理。

## 验证

- 本机：`tsc -b`、`eslint src`、`vite build` 通过；前端 103 项单测通过。
- 本机 CDP 13 项全过：默认环 opacity 0；0.9s 时环 opacity 1 且 dashoffset 39.5、无红底；1.5s 后红底 `rgb(211,47,47)` + 文案「已删除」+ 撤销 `z-index 6`；撤销后红底消失、按钮移除、`DELETE` 计数 0、列表仍 2 条；再长按至红色态，前 800ms 无 DELETE，渐隐采样 0.93 → 0.79 → 0.58 → 0.37，渐隐后 DELETE 1 次、列表剩 1 条；零控制台报错。
- 服务器：stage 70 文件 + 入口资产通过；switch 健康门禁 `status=ok`、决策层 `primary·jev`；公网 CSS 含 `#d32f2f` 与 `.hold-to-delete__undo`，JS 含「撤销」，两个入口资产哈希与本地一致。

## 回滚

```bash
ln -s /opt/aligo-travel/releases/release-20261126-144626-evidence-collapse /opt/aligo-travel/.current-rollback
mv -Tf /opt/aligo-travel/.current-rollback /opt/aligo-travel/current
systemctl restart aligo-travel.service
```

## 说明

- 撤销只回退界面状态，不涉及服务端：删除请求直到渐隐结束才发出，所以撤销窗口内数据未动。
- 浮空「撤销」按钮压在下一行卡片上（800ms 内），这是为了在 64px 行高里保持可点击浮层；若想去掉遮挡，可以改成在红色卡片内部右下角显示。
