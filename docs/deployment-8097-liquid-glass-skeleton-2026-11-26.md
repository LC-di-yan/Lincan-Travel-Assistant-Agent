# 8097 发布：液态玻璃 + 骨架屏流光（2026-11-26）

- 发布：`release-20261126-140049-liquid-glass`；回退：`release-20261126-092305-hold-to-delete`。
- 公网入口：`https://120.24.251.119:8097/`；发布记录 `/opt/aligo-travel/.deploy/20261126-140049-liquid-glass/`。
- 发布内容 93 个文件：70 个前端构建产物（新入口 `index-BnOXT_YE.js` / `index-Cxdf7nL9.css`）+ 23 个后端/Skill 文件（含新增 `utils/cn_numbers.py`）。

## 前端

- 首页 4 个示例按钮与聊天记录每一条换成液态玻璃：10px 背板模糊、1px 高光边、指针高光只写 `--mx` / `--my`；按下 `scaleX 1.05 / scaleY 0.86`，松手按 bounce 0.6 过冲一次；块下方不画厚边与投影。
- 白天模式玻璃比纸面深一档（`rgb(198 212 203 / 0.34)` 中间色）；暗色回到白玻璃 + 白字。
- 新增骨架屏流光 `SkeletonShimmer`：8 块、1400ms linear、逐块 +90ms、200% 高光带扫 `200% → -200%`，`role=status` + `aria-busy`，块 `aria-hidden`；接入结果卡懒加载与个人中心加载占位，数据到达整棵卸载并移除注入样式。
- 聊天记录条目保留长按 2 秒删除与进度环；删除条目、偏好、费用面板沿用原交互。

## 后端

- 口语与约束修复相关文件 22 处（`agents/`、`utils/`、`context/`、`server/`、`.claude/skills/`），新增 `utils/cn_numbers.py`。
- 变更来源是本次会话之前的口语识别修复工作，本次发布只做打包与验证，未改写其逻辑。

## 验证

- 本机：`pytest -q` **1205 passed / 16 skipped**；`tsc -b`、`eslint src`、`vite build` 通过；前端 102 项单测通过。
- 本机 CDP：骨架 25 项（8 块 / 260.0px / 延迟 0–630ms / 200%→-23.8% 扫动 / reduced-motion / 卸载无残留）、液态玻璃 20 项、结果卡集成 6 项，全部通过，零控制台报错。
- 服务器预检（stage）：93 个文件哈希校验、22 个 py 编译、`agents`+`utils`+`context`+`server`+`rag_core` 全量 compileall、14 个模块 import 冒烟；入口资产存在且被 `index.html` 引用。
- 切换门禁（switch）：`/api/health` 返回 `status=ok`、决策层 `primary/jev`、`last_error` 为空；`systemctl` 存活且进程 cwd 指向新 release；公网 `index.html` 含新入口、两个入口资产 gzip 一致且内容与 release 内文件 byte-for-byte 相同；`/api/history` 未认证仍 401；共享数据快照 73 个文件前后一致；8096 监听进程未变。
- 公网浏览器实测：`https://120.24.251.119:8097/` 加载 `index-BnOXT_YE.js`，4 个示例按钮均为玻璃（`backdrop-filter` 行内样式在），零控制台报错、零失败请求。

## 回滚

```bash
ln -s /opt/aligo-travel/releases/release-20261126-092305-hold-to-delete /opt/aligo-travel/.current-rollback
mv -Tf /opt/aligo-travel/.current-rollback /opt/aligo-travel/current
systemctl restart aligo-travel.service
```

## 说明

- 只发布 `web/dist` 与变更的后端/Skill 文件；`tests/`、`docs/`、`output/`、`private/` 与 `.env`、`data/` 未进入发布包。
- 服务器上旧构建遗留的静态资源仍保留（内容哈希命名、已无引用），供已打开的页面继续加载。
- 个人中心在线上是开启的，因此骨架屏结果卡与个人中心占位都会实际走到；结果卡的真实内容高度仍由内容决定，骨架卸载时会换高，这一点本地已记录为未达成项。
